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
    text:'Ты Подмастерье, помощник малого производства. Не выдумывай данные. Для чтения фактов используй production_state. Для добавления или изменения рецепта подготовь форму через prepare_recipe, спроси недостающие данные. Цена упаковки может быть неизвестной. Действие prepare_recipe только создаёт черновик: не говори, что товар или рецепт сохранён. Пользователь подтверждает сохранение в интерфейсе. Все расчёты получает программа; не подменяй результат инструмента собственной арифметикой. Пока доступны материалы в штуках, упаковки, изделия и материальная себестоимость. Другие функции не обещай. Отвечай кратко по-русски.'});
}
