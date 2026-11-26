import path from 'node:path';
export async function mountProductionMcp(ctx, client, {pythonExecutable, productDirectory, databasePath, scope, requestId, grant}) {
  for(const p of [pythonExecutable,productDirectory,databasePath])
    if(typeof p!=='string'||!path.isAbsolute(p)||p.includes('\0')) throw Error('Invalid private path');
  for(const v of [scope.actorId,scope.workspaceId,scope.chatId,requestId])
    if(typeof v!=='string'||!v||v.includes('\0')) throw Error('Invalid scope');
  if(!/^[A-Za-z0-9_-]{43}$/.test(grant?.token??'')) throw Error('Missing model grant');
  const config={serverName:'platform',transport:'stdio',command:pythonExecutable,cwd:productDirectory,
    args:['-m','platform_core.podmasterye_mcp','--db='+databasePath,'--actor='+scope.actorId,'--workspace='+scope.workspaceId,'--chat='+scope.chatId,'--request='+requestId],
    env:{PODMASTER_OPERATION_GRANT:grant.token},failOnStartupError:true,toolCallTimeoutMs:15000};
  const fiber=ctx.plugin(client,config);
  await fiber.await();
  if(fiber._error) throw fiber._error;
}
export function registerProductionContext(ctx){
  ctx.systemPrompt.section({name:'production-instructions',order:80,interpolate:false,
    text:'Ты Подмастерье — помощник малого производства. Используй только инструменты, доступные в текущем запросе. Список инструментов ограничен локальным фильтром; если нужного действия нет, уточни задачу. Факты и расчёты получай из серверных инструментов. Не выдумывай суммы, остатки и названия. Заполняй только известные поля, спроси недостающие. Если есть current_form, сначала прочитай его. Любой черновик формы требует подтверждения в кабинете; не утверждай, что запись сохранена. Не запрашивай и не заполняй секреты, пароли, платёжные и административные поля. Отвечай кратко по-русски.'});
}
