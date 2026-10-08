import { Bot, InputFile } from "grammy";
import { autoRetry } from "@grammyjs/auto-retry";
import { replyModeFor, type Config } from "../config.ts";
import type { RouteStore } from "../letta/store.ts";
import { log } from "../log.ts";
import { routeKeyString, type AgentBridge, type InboundFile, type InboundMessage, type RouteKey, type TurnContext, type TurnEvent } from "../types.ts";
import { createTranscriber, type Transcriber } from "../transcribe/index.ts";
import { ApprovalManager } from "./approvals.ts";
import { COMMANDS, parseCommand, runCommand } from "./commands.ts";
import { Debouncer, Deduper, gate, normalizeText, routeFor, surfaceDenial, type TelegramMessageLike } from "./ingress.ts";
import { createRenderer, sendFormatted, type TelegramApiLike } from "./renderer.ts";

export interface TelegramRuntime { bot: Bot; approvals:ApprovalManager; ready():boolean; stop():Promise<void>; }
interface Pending { route:RouteKey; inbound:InboundMessage; }
const refusalAt=new Map<string,number>();

export function createTelegramBot(token:string):Bot { const bot=new Bot(token); bot.api.config.use(autoRetry()); return bot; }
export function transcriberFromConfig(config:Config):Transcriber|undefined { if(config.TRANSCRIBE_PROVIDER==="none")return;return createTranscriber({provider:config.TRANSCRIBE_PROVIDER,apiKey:config.TRANSCRIBE_API_KEY,model:config.TRANSCRIBE_MODEL,baseUrl:config.TRANSCRIBE_BASE_URL,language:config.TRANSCRIBE_LANGUAGE,timeoutMs:config.TRANSCRIBE_TIMEOUT_SECONDS*1000}); }

async function download(api:any,token:string,fileId:string,max:number,timeoutMs:number):Promise<{data:Blob;path:string}> {
  const file=await api.getFile(fileId);if(!file.file_path)throw new Error("Telegram did not return a file path.");
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);timer.unref?.();
  try { const response=await fetch(`https://api.telegram.org/file/bot${token}/${file.file_path}`,{signal:controller.signal});if(!response.ok||!response.body)throw new Error(`File download failed (${response.status}).`);const declared=Number(response.headers.get("content-length")??0);if(declared>max)throw new Error(`File exceeds ${max} bytes.`);const reader=response.body.getReader(),parts:Uint8Array[]=[];let size=0;for(;;){const {done,value}=await reader.read();if(done)break;if(value){size+=value.byteLength;if(size>max){await reader.cancel();throw new Error(`File exceeds ${max} bytes.`)}parts.push(value)}}const bytes=new Uint8Array(size);let at=0;for(const part of parts){bytes.set(part,at);at+=part.byteLength}return{data:new Blob([bytes]),path:file.file_path}; } finally {clearTimeout(timer)}
}
function media(m:any,maxImageBytes=Number.MAX_SAFE_INTEGER):{fileId:string;name:string;type:string;size:number;image:boolean;voice?:boolean;duration?:number}|null {
  if(m.photo?.length){const choices=[...m.photo].sort((a:any,b:any)=>(b.file_size??0)-(a.file_size??0));const p=choices.find((photo:any)=>!photo.file_size||photo.file_size<=maxImageBytes);return p?{fileId:p.file_id,name:`photo-${m.message_id}.jpg`,type:"image/jpeg",size:p.file_size??0,image:true}:null;}
  const entries:[[string,any,string,boolean,boolean?],...[string,any,string,boolean,boolean?][]]=[["document",m.document,m.document?.mime_type??"application/octet-stream",false],["audio",m.audio,m.audio?.mime_type??"audio/mpeg",false],["video",m.video,m.video?.mime_type??"video/mp4",false],["animation",m.animation,m.animation?.mime_type??"video/mp4",false],["voice",m.voice,m.voice?.mime_type??"audio/ogg",false,true],["sticker",m.sticker,m.sticker?.is_animated||m.sticker?.is_video?"":"image/webp",false]];
  for(const [kind,x,type,image,voice] of entries)if(x&&type)return{fileId:x.file_id,name:x.file_name??`${kind}-${m.message_id}${type==="image/webp"?".webp":""}`,type,size:x.file_size??0,image,voice,duration:x.duration};return null;
}
async function normalize(config:Config,api:any,token:string,m:any,route:RouteKey,botId:string,username:string,transcriber?:Transcriber):Promise<InboundMessage>{const inbound=normalizeText(m,route,botId,username),item=media(m,config.MAX_IMAGE_BYTES);if(!item)return inbound;const cap=item.image?config.MAX_IMAGE_BYTES:config.MAX_FILE_BYTES;if(item.size&&item.size>cap)return inbound;const got=await download(api,token,item.fileId,cap,config.DOWNLOAD_TIMEOUT_SECONDS*1000);const bytes=new Uint8Array(await got.data.arrayBuffer());if(item.image){inbound.images.push({name:item.name,mediaType:item.type as "image/jpeg",base64:Buffer.from(bytes).toString("base64")});return inbound;}const f:InboundFile={name:item.name,contentType:item.type,size:bytes.byteLength,data:new Blob([bytes],{type:item.type}),...(item.voice?{voice:true}:{}),...(item.duration!==undefined?{durationSecs:item.duration}:{})};if(transcriber&&(/audio/.test(item.type)||item.voice)){try{const t=await transcriber.transcribe({data:f.data!,filename:f.name,contentType:item.type});f.transcript=t.text;f.transcriptProvider=t.provider;f.transcriptModel=t.model}catch(error){f.transcriptError=error instanceof Error?error.message:"Transcription failed"}}inbound.files.push(f);return inbound;}

export async function startTelegram(config:Config,bridge:AgentBridge,store:RouteStore,bot=createTelegramBot(config.TELEGRAM_BOT_TOKEN)):Promise<TelegramRuntime>{
  const api=bot.api as any,approvals=new ApprovalManager(config,api),dedupe=new Deduper(),transcriber=transcriberFromConfig(config);let ready=false,stopping=false;
  await bot.init();const me=bot.botInfo;ready=true;
  const debouncer=new Debouncer<Pending>(config.DEBOUNCE_MS,(_key,items)=>{const first=items[0];if(first)void dispatch(first.route,items)});
  const albums=new Map<string,{items:any[];timer:ReturnType<typeof setTimeout>}>();
  function renderer(route:RouteKey,trigger?:string){return createRenderer(api as TelegramApiLike,config,route,trigger,replyModeFor(config,route));}
  bridge.onBackground((route:RouteKey)=>{const render=renderer(route);return(e:TurnEvent)=>void render(e)});
  async function dispatch(route:RouteKey,items:Pending[]){const last=items.at(-1)!;const render=renderer(route,last.inbound.messageId);const ctx:TurnContext={route,triggerMessageId:last.inbound.messageId,requesterId:last.inbound.authorId,onEvent:e=>void render(e),requestApproval:req=>approvals.request(req)};try{await bridge.submit(items.map(i=>i.inbound),ctx)}catch(error){log.error("Telegram dispatch failed",{route:routeKeyString(route),err:String(error)})}}
  async function processMessages(messages:any[]){if(stopping)return;messages=messages.filter(item=>dedupe.firstTime(`${item.chat.id}:${item.message_id}`));const m=messages[0] as TelegramMessageLike;if(!m)return;const id=`${m.chat.id}:${m.message_id}`;
    const denial=surfaceDenial(config,m);if(denial){if(m.chat.type==="private"&&m.from){const uid=String(m.from.id),now=Date.now();if(now-(refusalAt.get(uid)??0)>60_000){refusalAt.set(uid,now);await api.sendMessage(m.chat.id,`Sorry, user ${uid} is not allowed to use this bot.`).catch(()=>{})}}return;}
    if(m.migrate_to_chat_id){store.rename(String(m.chat.id),String(m.migrate_to_chat_id));log.info("Telegram group migrated",{from:String(m.chat.id),to:String(m.migrate_to_chat_id)});return;}
    const decision=gate(config,m,String(me.id),me.username);if(!decision.accept)return;
    const command=parseCommand(m.text??m.caption??"",me.username);if(command){const response=await runCommand(command,decision.route,String(m.from!.id),config,bridge);await sendFormatted(api,decision.route,response,String(m.message_id));return;}
    try{const normalized:InboundMessage[]=[];for(const part of messages)normalized.push(await normalize(config,api,config.TELEGRAM_BOT_TOKEN,part,routeFor(part),String(me.id),me.username,transcriber));if(!normalized.some(x=>x.text||x.images.length||x.files.length))return;if(normalized.length>1){const pending=normalized.map(inbound=>({route:inbound.route,inbound}));await dispatch(pending[0]!.route,pending)}else{const inbound=normalized[0]!;debouncer.push(`${routeKeyString(inbound.route)}:${inbound.authorId}`,{route:inbound.route,inbound})}}catch(error){for(const item of messages)dedupe.forget(`${item.chat.id}:${item.message_id}`);log.warn("Telegram message normalization failed",{chat:String(m.chat.id),message:String(m.message_id),err:String(error)})}
  }
  bot.on("message",async ctx=>{const m=ctx.message as any;if(m.media_group_id){const key=`${m.chat.id}:${m.media_group_id}`;const old=albums.get(key);if(old){clearTimeout(old.timer);old.items.push(m);old.timer=setTimeout(()=>{albums.delete(key);void processMessages(old.items)},300)}else{const entry={items:[m],timer:setTimeout(()=>{},300)};entry.timer=setTimeout(()=>{albums.delete(key);void processMessages(entry.items)},300);albums.set(key,entry)}return;}await processMessages([m]);});
  bot.on("callback_query:data",async ctx=>{const q=ctx.callbackQuery,msg=q.message as any;if(!msg)return void ctx.answerCallbackQuery();const probe={...msg,from:q.from} as TelegramMessageLike;const denial=surfaceDenial(config,probe);if(denial){await ctx.answerCallbackQuery({text:"You are not allowed to use this bot.",show_alert:true});return;}await approvals.handle(q.id,String(q.from.id),q.data);});
  bot.catch(error=>log.error("Telegram update failed",{err:error.message}));
  if(config.REGISTER_COMMANDS)await api.setMyCommands(COMMANDS).catch((error:unknown)=>log.warn("Telegram command registration failed",{err:String(error)}));
  log.info("Telegram long polling starting; any configured webhook will be removed",{username:me.username});
  void bot.start({allowed_updates:["message","callback_query"]}).catch(error=>{ready=false;if(!stopping)log.error("Telegram polling stopped",{err:String(error)})});
  return{bot,approvals,ready:()=>ready,async stop(){stopping=true;ready=false;for(const x of albums.values())clearTimeout(x.timer);albums.clear();const dropped=debouncer.clear();if(dropped)log.warn("dropped debounced Telegram messages on shutdown",{count:dropped});await approvals.cancelAll();await bot.stop().catch(()=>{});}};
}

export { InputFile };
