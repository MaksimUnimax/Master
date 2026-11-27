import path from 'node:path';
export async function mountProductionMcp(ctx, client, {pythonExecutable, productDirectory, databasePath, scope, requestId, grant}) {
  for(const p of [pythonExecutable,productDirectory,databasePath])
    if(typeof p!=='string'||!path.isAbsolute(p)||p.includes('\0')) throw Error('Invalid private path');
  for(const v of [scope.actorId,scope.workspaceId,scope.chatId,requestId])
    if(typeof v!=='string'||!v||v.includes('\0')) throw Error('Invalid scope');
  if(!/^[A-Za-z0-9_-]{43}$/.test(grant?.token??'')) throw Error('Missing model grant');
  const config={serverName:'platform',transport:'stdio',command:pythonExecutable,cwd:productDirectory,
    args:['-m','platform_core.podmasterye_mcp','--db='+databasePath,'--actor='+scope.actorId,'--workspace='+scope.workspaceId,'--chat='+scope.chatId,'--request='+requestId],
    env:{PODMASTER_OPERATION_GRANT:grant.token,PODMASTERYE_MULTI_WORKSHOP:process.env.PODMASTERYE_MULTI_WORKSHOP==="1"?"1":"0"},failOnStartupError:true,toolCallTimeoutMs:15000};
  const fiber=ctx.plugin(client,config);
  await fiber.await();
  if(fiber._error) throw fiber._error;
}
export function registerProductionContext(ctx){
  ctx.systemPrompt.section({name:'production-instructions',order:80,interpolate:false,
    text:'Ты Подмастерье — помощник малого производства, ведёшь обычный диалог с зарегистрированным пользователем. Если задача известна, приложение может ответить без модели; такие ответы находятся в общей истории. Отвечай по существу. Для данных мастерской используй серверные инструменты, не выдумывай суммы и остатки. Не загружай весь каталог форм: form_catalog(form) возвращает поля выбранной формы. При дополнении формы сначала прочитай current_form. Заполняй только известные поля; хозяйственные записи требуют подтверждения в кабинете. Не запрашивай и не заполняй секреты, пароли, платёжные и административные поля. Отвечай на языке пользователя.'+(process.env.PODMASTERYE_MULTI_WORKSHOP==='1'?'':' Сейчас у аккаунта одна доступная мастерская; создавать дополнительные или переключать мастерские нельзя. Не обещай такие действия.')});
}
