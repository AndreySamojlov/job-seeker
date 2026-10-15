// Runs only with an authorized in-app Browser tab on the synthetic fixture18768.
import assert from 'node:assert/strict';

export async function runBoardSmoke(tab) {
  const ui = tab.playwright;
  await ui.getByRole('button', {name:'Greenhouse', exact:true}).click();
  await ui.locator('.ce-board-pager').filter({hasText:'1–100 / 201'}).waitFor({state:'visible'});
  assert.equal(await ui.locator('.ch-main canvas').count(), 1);
  assert.equal(await ui.locator('.ch-minis canvas').count(), 3);
  await ui.getByRole('button', {name:'Далее', exact:true}).click();
  await ui.locator('.ce-board-pager').filter({hasText:'101–200 / 201'}).waitFor({state:'visible'});
  await ui.getByRole('combobox', {name:'Кандидат', exact:true}).selectOption('beta');
  await ui.locator('.ce-board-pager').filter({hasText:'1–100 / 201'}).waitFor({state:'visible'});
  await ui.getByRole('combobox', {name:'Борд', exact:true}).selectOption('slow');
  await ui.getByRole('combobox', {name:'Борд', exact:true}).selectOption('empty');
  await ui.locator('.ce-board-pager').filter({hasText:'0–0 / 0'}).waitFor({state:'visible'});
  assert.equal(await ui.locator('tbody tr').count(), 0);
  await ui.getByRole('combobox', {name:'Борд', exact:true}).selectOption('fail');
  await ui.getByRole('status').filter({hasText:'Данные недоступны'}).waitFor({state:'visible'});
  assert.equal(await ui.locator('canvas').count(), 0);
  await ui.getByRole('button', {name:'Greenhouse', exact:true}).click();
  await ui.locator('.ce-board-pager').filter({hasText:'1–100 / 201'}).waitFor({state:'visible'});
  await ui.getByRole('button', {name:'Показать график: Дата обнаружения и фит', exact:true}).click();
  assert.equal(await ui.locator('.ch-main h3').innerText(), 'Дата обнаружения и фит');
  await ui.getByRole('button', {name:'Развернуть график', exact:true}).click();
  assert.equal(await ui.getByRole('dialog').isVisible(), true);
  await ui.getByRole('dialog').press('Escape');
  return {passed:['four charts','paging','candidate filter','late responses','empty','503 clear','recovery','promotion','modal']};
}
