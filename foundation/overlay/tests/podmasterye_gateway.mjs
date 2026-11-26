// Local Messages fixture; no real provider requests.
import http from 'node:http';
import {once} from 'node:events';
import {createGateway} from '../../../integrations/harness-native-lab/gateway/server.mjs';
import {openOperationResolver} from '../../../integrations/harness-native-lab/gateway/operation-resolver.mjs';
const [db,journal]=process.argv.slice(2);
let calls=0;
const upstream=http.createServer(async(req,res)=>{
  const chunks=[];for await(const c of req)chunks.push(c);
  const q=JSON.parse(Buffer.concat(chunks));
  const last=q.messages.findLast(x=>x.role==='user').content;
  const result=last.find(x=>x.type==='tool_result');
  const text=last.find(x=>x.type==='text')?.text||'';
  if(text==='uncertain fixture'){res.writeHead(503,{'content-type':'application/json'});res.end('{"error":{"type":"api_error","message":"fixture"}}');return;}
  const tool=q.tools?.find(t=>t.name==='mcp__platform__prepare_recipe');
  const draft=!result&&text.includes('Свободная формулировка');
  if(draft&&!tool){res.writeHead(422);res.end('missing built-in tool');return;}
  if(result&&(result.is_error||!JSON.stringify(result.content).includes('80.00'))){res.writeHead(422);res.end('invalid draft');return;}
  const event=(type,fields={})=>res.write('event: '+type+'\ndata: '+JSON.stringify({type,...fields})+'\n\n');
  res.writeHead(200,{'content-type':'text/event-stream'});
  event('message_start',{message:{id:'fixture-'+ ++calls,role:'assistant',type:'message',content:[],model:q.model,usage:{input_tokens:10,output_tokens:0,cache_read_input_tokens:0,cache_creation_input_tokens:0}}});
  if(draft){
    event('content_block_start',{index:0,content_block:{type:'tool_use',id:'prepare-1',name:tool.name,input:{}}});
    event('content_block_delta',{index:0,delta:{type:'input_json_delta',partial_json:JSON.stringify({material:'Бусины',product:'Браслет',pack_quantity:400,usage_quantity:40,pack_price:'800'})}});
  }else{
    event('content_block_start',{index:0,content_block:{type:'text',text:''}});
    event('content_block_delta',{index:0,delta:{type:'text_delta',text:'Ответ тестовой модели.'}});
  }
  event('content_block_stop',{index:0});
  event('message_delta',{delta:{stop_reason:draft?'tool_use':'end_turn'},usage:{output_tokens:5}});
  event('message_stop');res.end();
});
async function listen(s){s.listen(0,'127.0.0.1');await once(s,'listening');return 'http://127.0.0.1:'+s.address().port;}
const resolver=openOperationResolver(db);
const gateway=createGateway({resolveAttribution:resolver.resolve,billing:resolver.billing,upstreamBase:await listen(upstream),now:()=>Date.UTC(2026,10,20,7),realKey:'local-fixture',logFile:journal,fx:80});
console.log(await listen(gateway.server));process.stdin.resume();
process.stdin.on('end',()=>{gateway.server.close();upstream.close();gateway.server.closeAllConnections();upstream.closeAllConnections();resolver.close();});
