import { randomUUID } from "node:crypto";
import type { Config } from "../config.ts";
import { log } from "../log.ts";
import type { ApprovalDecision, ApprovalRequest } from "../types.ts";
import { escapeHtml } from "./format.ts";

export interface ApprovalApi {
  sendMessage(chatId: string, text: string, options: Record<string, unknown>): Promise<{ message_id: number }>;
  editMessageText(chatId: string, messageId: number, text: string, options?: Record<string, unknown>): Promise<unknown>;
  answerCallbackQuery(id: string, options?: Record<string, unknown>): Promise<unknown>;
}
type Verdict = { state: "Approved"|"Denied"|"Timed out"|"Cancelled"|"Failed"; by?: string };
interface Pending { id:string; req:ApprovalRequest; message:number|null; timer:ReturnType<typeof setTimeout>|null; terminal:Verdict|null; resolve:(d:ApprovalDecision)=>void; }

export function previewInput(input: Record<string, unknown>, max=700): string { let value:string; try { value=JSON.stringify(input)??"{}"; } catch { value="[unserializable input]"; } return value.length>max?`${value.slice(0,max-1)}…`:value; }

export class ApprovalManager {
  private readonly pending=new Map<string,Pending>();
  constructor(private readonly config:Config,private readonly api:ApprovalApi){}
  get pendingCount(){return this.pending.size;}

  async request(req:ApprovalRequest):Promise<ApprovalDecision>{
    const mode=req.approvalMode??this.config.APPROVAL_MODE;
    if(mode==="allow")return{allow:true};
    if(mode==="deny")return{allow:false,message:`Tool ${req.toolName} requires approval, which is disabled.`};
    if(mode==="admins"&&!this.config.TELEGRAM_ADMIN_USER_IDS.length)return{allow:false,message:`Tool ${req.toolName} needs an admin's approval, but no Telegram admins are configured.`};
    const id=randomUUID().replace(/-/g,"").slice(0,12);
    return new Promise(resolve=>{
      const p:Pending={id,req,message:null,timer:null,terminal:null,resolve};
      this.pending.set(id,p);
      p.timer=setTimeout(()=>void this.settle(id,{allow:false,message:"Approval timed out"},{state:"Timed out"}),Math.max(0,this.config.APPROVAL_TIMEOUT_SECONDS*1000));
      p.timer.unref?.();
      this.api.sendMessage(req.route.chatId,this.render(req,null,false),{
        parse_mode:"HTML",...(req.route.topicId?{message_thread_id:Number(req.route.topicId)}:{}),
        reply_markup:{inline_keyboard:[[{text:"Approve",callback_data:`ap:${id}:y`},{text:"Deny",callback_data:`ap:${id}:n`}]]},
      }).then(message=>{
        p.message=message.message_id;
        if(p.terminal)void this.edit(p,p.terminal);
        else void this.api.editMessageText(req.route.chatId,message.message_id,this.render(req,null,false),{
          parse_mode:"HTML",reply_markup:{inline_keyboard:[[{text:"Approve",callback_data:`ap:${id}:y`},{text:"Deny",callback_data:`ap:${id}:n`}]]},
        }).catch(()=>{});
      }).catch(error=>{log.warn("approval message send failed",{tool:req.toolName,err:String(error)});void this.settle(id,{allow:false,message:"Approval could not be requested."},{state:"Failed"});});
    });
  }

  async handle(callbackId:string,userId:string,data:string):Promise<boolean>{
    const match=/^ap:([a-f0-9]{12}):([yn])$/.exec(data);if(!match)return false;
    const p=this.pending.get(match[1]!);
    if(!p){await this.api.answerCallbackQuery(callbackId,{text:"This approval is no longer active.",show_alert:true}).catch(()=>{});return true;}
    const mode=p.req.approvalMode??this.config.APPROVAL_MODE;
    const authorized=this.config.TELEGRAM_ADMIN_USER_IDS.includes(userId)||(mode==="requester"&&userId===p.req.requesterId);
    if(!authorized){await this.api.answerCallbackQuery(callbackId,{text:"You cannot decide this approval.",show_alert:true}).catch(()=>{});return true;}
    await this.api.answerCallbackQuery(callbackId).catch(()=>{});
    const allow=match[2]==="y";
    await this.settle(p.id,{allow,decidedBy:userId,...(!allow?{message:`A Telegram approver denied ${p.req.toolName}.`}:{})},{state:allow?"Approved":"Denied",by:userId});
    return true;
  }
  async cancelAll(message="Approval cancelled: the bot is shutting down."){await Promise.all([...this.pending.keys()].map(id=>this.settle(id,{allow:false,message},{state:"Cancelled"})));}
  private async settle(id:string,decision:ApprovalDecision,verdict:Verdict){const p=this.pending.get(id);if(!p)return false;this.pending.delete(id);if(p.timer)clearTimeout(p.timer);p.timer=null;p.terminal=verdict;p.resolve(decision);await this.edit(p,verdict);return true;}
  private async edit(p:Pending,verdict:Verdict){if(p.message===null)return;await this.api.editMessageText(p.req.route.chatId,p.message,this.render(p.req,verdict,true),{parse_mode:"HTML",reply_markup:{inline_keyboard:[]}}).catch(error=>log.debug("approval edit failed",{err:String(error)}));}
  private render(req:ApprovalRequest,verdict:Verdict|null,_disabled:boolean){const state=verdict?`${verdict.state}${verdict.by?` by ${verdict.by}`:""}`:"Approval needed";return `<b>${escapeHtml(state)}</b>\nTool: <code>${escapeHtml(req.toolName)}</code>\n<pre>${escapeHtml(previewInput(req.toolInput))}</pre>`;}
}
