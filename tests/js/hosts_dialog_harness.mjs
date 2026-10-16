// Обвязка для tests/test_hosts_dialog_logic_js.py: исполняет настоящие модули
// диалога хостов (app/dashboard/src/components/hostsDialog/*.ts) в Node — он
// сам снимает типы с .ts. Зависимостей нет.
//
// Вход (argv[2], JSON):
//   { op: "same", a, b }                     → { same: boolean }
//   { op: "visible", steps: [{ rowIds, hosts, filters }] }
//                                            → { steps: [[index, ...], ...] }
//   { op: "botOrder", steps: [{ rowIds, isAvailable, key }] }
//                                            → { steps: [[index, ...], ...] }
//   { op: "selectAllBots" | "withoutUnboundRentals", args: [...] }
//                                            → { result }
// В "visible" шаги идут подряд с общим состоянием «уже показанных» — как
// перерисовки списка, пока пользователь правит хосты и меняет фильтры.
import { isSameHostValues } from "../../app/dashboard/src/components/hostsDialog/hostValues.ts";
import * as botBindings from "../../app/dashboard/src/components/hostsDialog/botBindings.ts";
import {
  orderBotTabRows,
  selectVisibleHosts,
} from "../../app/dashboard/src/components/hostsDialog/hostsFilter.ts";

const scenario = JSON.parse(process.argv[2]);
let result;

if (scenario.op === "same") {
  result = { same: isSameHostValues(scenario.a, scenario.b) };
} else if (scenario.op === "visible") {
  let shown = null;
  const steps = scenario.steps.map(({ rowIds, hosts, filters }) => {
    const out = selectVisibleHosts(rowIds, hosts, filters, shown);
    shown = out.shown;
    return out.indexes;
  });
  result = { steps };
} else if (scenario.op === "botOrder") {
  let state = null;
  const steps = scenario.steps.map(({ rowIds, isAvailable, key }) => {
    const out = orderBotTabRows(rowIds, isAvailable, key, state);
    state = out.state;
    return out.order;
  });
  result = { steps };
} else if (scenario.op in botBindings) {
  result = { result: botBindings[scenario.op](...scenario.args) };
} else {
  throw new Error(`unknown op: ${scenario.op}`);
}

process.stdout.write(JSON.stringify(result));
