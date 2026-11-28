// Local model protocol fixture for multiple real tools in one native turn.
// No provider, storage or execution behavior is mocked here.
export function marketDualFixture(request,res,last,nextId){
 const marker='fixture-dual-sequence:';
 const user=last.find(b=>b.type==='text'&&b.text.includes(marker))?.text;
 const previous=last.find(b=>b.type==='tool_result'&&b.tool_use_id?.startsWith('dual-sequence-'));
 if(!user&&!previous)return false;
 const source=user||request.messages.toReversed().flatMap(m=>Array.isArray(m.content)?m.content:[]).find(b=>b.type==='text'&&b.text.includes(marker))?.text;
 const calls=JSON.parse(source.slice(source.indexOf(marker)+marker.length));
 const index=previous?Number(previous.tool_use_id.split('-')[2])+1:0,call=calls[index];
 if(call&&!request.tools.some(t=>t.name===call.name)){res.writeHead(422);res.end('missing real native tool');return true;}
 const id=nextId(),event=(type,fields={})=>res.write('event: '+type+'\ndata: '+JSON.stringify({type,...fields})+'\n\n');
 res.writeHead(200,{'content-type':'text/event-stream'});
 event('message_start',{message:{id:'dual-response-'+id,role:'assistant',type:'message',content:[],model:request.model,usage:{input_tokens:10,output_tokens:0,cache_read_input_tokens:0,cache_creation_input_tokens:0}}});
 event('content_block_start',{index:0,content_block:call?{type:'tool_use',id:'dual-sequence-'+index+'-'+id,name:call.name,input:{}}:{type:'text',text:''}});
 event('content_block_delta',{index:0,delta:call?{type:'input_json_delta',partial_json:JSON.stringify(call.input)}:{type:'text_delta',text:JSON.stringify(previous.content)}});
 event('content_block_stop',{index:0});event('message_delta',{delta:{stop_reason:call?'tool_use':'end_turn'},usage:{output_tokens:5}});
 event('message_stop');res.end();return true;
}
