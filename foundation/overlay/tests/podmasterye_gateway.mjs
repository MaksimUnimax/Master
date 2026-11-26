// Local Messages fixture; no real provider requests.
import http from 'node:http';
import {once} from 'node:events';
import {join,dirname} from 'node:path';
import {appendFileSync} from 'node:fs';
import {journalVision} from '../native/verified-vision.mjs';
import {createGateway} from '../../../integrations/harness-native-lab/gateway/server.mjs';
import {openOperationResolver} from '../../../integrations/harness-native-lab/gateway/operation-resolver.mjs';
const [db,journal]=process.argv.slice(2);
let calls=0;
const upstream=http.createServer(async(req,res)=>{
  const chunks=[];for await(const c of req)chunks.push(c);
  const q=JSON.parse(Buffer.concat(chunks));
  appendFileSync(journal+".requests",JSON.stringify(q)+"\n",{mode:0o600});
  const last=q.messages.findLast(x=>x.role==='user').content;
  const result=last.find(x=>x.type==='tool_result');
  const text=last.filter(x=>x.type==='text').map(x=>x.text).join("\n");
  // Exercise the real native read_chat_file tool and image injection.
  const fileStep=result?.tool_use_id;
  const fileRequest=/(Разбери приложенные файлы|Прочитай приложенный файл|Что было в предыдущем файле|Проверь страницу PDF|Проверь изображение)/.test(text);
  if(fileRequest||['file-list','file-list-pdf','file-read','file-page'].includes(fileStep)){
    const event=(type,fields={})=>res.write('event: '+type+'\n'+'data: '+JSON.stringify({type,...fields})+'\n\n');
    const fileTool=q.tools?.find(t=>t.name==='read_chat_file');
    let call,answer;
    if(fileStep==='file-list'||fileStep==='file-list-pdf'){
      const id=JSON.stringify(result.content).match(/[a-f0-9]{32}/)?.[0];
      if(!id){res.writeHead(422);res.end('missing real file id');return;}
      call={id:fileStep==='file-list-pdf'?'file-page':'file-read',name:fileTool.name,input:{id,...(fileStep==='file-list-pdf'?{page:1}:{})}};
    }else if(fileStep==='file-read'){
      if(result.is_error||!JSON.stringify(result.content).includes('714598')){res.writeHead(422);res.end('missing actual spreadsheet value');return;}
      answer='Маркер отчёта: 714598.';
    }else if(fileStep==='file-page'||text.includes('Проверь изображение')){
      if(!q.messages.some(m=>Array.isArray(m.content)&&m.content.some(b=>b.type==='image'&&b.source?.data?.length>30))){res.writeHead(422);res.end('missing real image pixels');return;}
      answer=fileStep==='file-page'?'Пиксели страницы PDF получены.':'Изображение получено.';
    }else{
      if(!fileTool){res.writeHead(422);res.end('missing native attachment reader');return;}
      if(text.includes('контекст')&&!JSON.stringify(q.messages).includes('покажи чистую прибыль')){res.writeHead(422);res.end('missing local conversation context');return;}
      call={id:text.includes('Проверь страницу PDF')?'file-list-pdf':'file-list',name:fileTool.name,input:{}};
    }
    res.writeHead(200,{'content-type':'text/event-stream'});
    event('message_start',{message:{id:'fixture-'+ ++calls,role:'assistant',type:'message',content:[],model:q.model,usage:{input_tokens:10,output_tokens:0,cache_read_input_tokens:0,cache_creation_input_tokens:0}}});
    if(call){
      event('content_block_start',{index:0,content_block:{type:'tool_use',id:call.id,name:call.name,input:{}}});
      event('content_block_delta',{index:0,delta:{type:'input_json_delta',partial_json:JSON.stringify(call.input)}});
    }else{
      event('content_block_start',{index:0,content_block:{type:'text',text:''}});
      event('content_block_delta',{index:0,delta:{type:'text_delta',text:answer}});
    }
    event('content_block_stop',{index:0});
    event('message_delta',{delta:{stop_reason:call?'tool_use':'end_turn'},usage:{output_tokens:5}});
    event('message_stop');res.end();return;
  }
  if(text.startsWith('uncertain fixture:')){res.writeHead(503,{'content-type':'application/json'});res.end('{"error":{"type":"api_error","message":"fixture"}}');return;}
  const partial=text.includes('Тест частичной закупки');
  const continuation=text.includes('Тест дополнения закупки');
  const settings=text.includes('Тест заполнения мастерской');
  const accounting=text.includes('Тест свободной закупки')||partial||continuation;
  const report=text.includes('Тест свободного отчёта');
  const tool=q.tools?.find(t=>t.name==='mcp__platform__'+(settings?'prepare_form':accounting?'prepare_accounting':report?'accounting_report':'prepare_recipe'));
  const draft=!result&&(text.includes('Свободная формулировка')||accounting||report||settings);
  const pressure=text.includes('fixture-pressure:');
  const compact=text.includes('You are now acting as a compaction engine');

  // Stable, complete draft/read tool contract; no lexical filter may hide it.
  if(!result&&accounting&&!tool?.input_schema?.properties?.operation?.enum?.includes('purchase')){res.writeHead(422);res.end('missing purchase operation');return;}
  if(draft&&!tool){res.writeHead(422);res.end('missing built-in tool');return;}
  if(result&&(result.is_error||!['80.00','800.00','1600.00','inventory_rub','missing','workshop_create'].some(x=>JSON.stringify(result.content).includes(x)))){res.writeHead(422);res.end('invalid draft or report');return;}
  const event=(type,fields={})=>res.write('event: '+type+'\ndata: '+JSON.stringify({type,...fields})+'\n\n');
  res.writeHead(200,{'content-type':'text/event-stream'});
  event('message_start',{message:{id:'fixture-'+ ++calls,role:'assistant',type:'message',content:[],model:q.model,usage:{input_tokens:10,output_tokens:0,cache_read_input_tokens:pressure?50000:0,cache_creation_input_tokens:0}}});
  if(draft){
    event('content_block_start',{index:0,content_block:{type:'tool_use',id:'prepare-1',name:tool.name,input:{}}});
    event('content_block_delta',{index:0,delta:{type:'input_json_delta',partial_json:JSON.stringify(settings?{form:'workshop_create',arguments:{name:'Новая мастерская',description:'Проверка'}}:partial?{operation:'purchase',arguments:{material:'Бусины',quantity:2}}:continuation?{operation:'purchase',arguments:{total:'1600'}}:accounting?{operation:'purchase',arguments:{material:'Бусины',quantity:1,purchase_unit:'pack',total:'800'}}:report?{view:'summary'}:{material:'Бусины',product:'Браслет',pack_quantity:400,usage_quantity:40,pack_price:'800'})}});
  }else{
    event('content_block_start',{index:0,content_block:{type:'text',text:''}});
    event('content_block_delta',{index:0,delta:{type:'text_delta',text:compact?'## Primary Request and Intent\n- Сохранить контекст проверки. Контрольная запись 0.':'Ответ тестовой модели.'}});
  }
  event('content_block_stop',{index:0});
  event('message_delta',{delta:{stop_reason:draft?'tool_use':'end_turn'},usage:{output_tokens:5}});
  event('message_stop');res.end();
});
async function listen(s){s.listen(0,'127.0.0.1');await once(s,'listening');return 'http://127.0.0.1:'+s.address().port;}
const resolver=openOperationResolver(db);
const vision=journalVision(join(dirname(db),'chats','native-chats.sqlite3'),resolver.resolve);
const gateway=createGateway({attachVision:vision.attach,resolveAttribution:resolver.resolve,billing:resolver.billing,upstreamBase:await listen(upstream),now:()=>Date.UTC(2026,10,20,7),realKey:'local-fixture',logFile:journal,fx:80});
console.log(await listen(gateway.server));process.stdin.resume();
process.stdin.on('end',()=>{gateway.server.close();upstream.close();gateway.server.closeAllConnections();upstream.closeAllConnections();vision.close();resolver.close();});
