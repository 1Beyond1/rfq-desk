/* Request ownership, independent of DOM, transport and business rules. */
class RfqInteraction {
 constructor(){this.epoch=0;this.desired=null;this.sequence=0;this.pending=new Map()}
 navigate(caseId){this.desired=caseId;return {epoch:++this.epoch,caseId,taskId:++this.sequence}}
 capture(c){if(!c||this.desired!==c.id)throw Error('案件正在切换，请待目标案件载入后操作');return {epoch:this.epoch,caseId:c.id,revision:c.revision,title:c.title,taskId:++this.sequence}}
 active(ctx,c){return ctx.epoch===this.epoch&&this.desired===ctx.caseId&&c?.id===ctx.caseId}
 canDisplayNavigation(ctx,c,response){return this.navigationActive(ctx)&&response.id===ctx.caseId&&(c?.id!==response.id||response.revision>=c.revision)}
 navigationActive(ctx){return ctx.epoch===this.epoch&&this.desired===ctx.caseId}
 begin(ctx,key){const id=ctx.caseId+':'+key;if(this.pending.has(id))throw Error('同一操作正在提交，请等待结果；未发送重复请求');const task={...ctx,key:id,taskId:++this.sequence};this.pending.set(id,task.taskId);return task}
 finish(task){if(this.pending.get(task.key)===task.taskId)this.pending.delete(task.key)}
 busy(caseId,key){return this.pending.has(caseId+':'+key)}
 canApply(ctx,c,response){return this.active(ctx,c)&&response.id===ctx.caseId&&response.revision>=c.revision}
 static clearSubmitted(drafts,key,submitted){if(drafts.get(key)===submitted)drafts.delete(key)}
}
if(typeof module!=='undefined')module.exports=RfqInteraction;
if(typeof window!=='undefined')window.RfqInteraction=RfqInteraction;
