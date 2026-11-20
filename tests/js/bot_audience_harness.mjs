import {
  isSingleSubscription,
  isSoloPanel,
  previewHostList,
} from "../../app/dashboard/src/utils/botAudience.ts";

const scenario = JSON.parse(process.argv[2]);
let result;
if (scenario.op === "flags") {
  result = {
    solo: isSoloPanel(scenario.botCount),
    single: isSingleSubscription(scenario.botCount),
  };
} else if (scenario.op === "preview") {
  result = {
    remarks: previewHostList(
      scenario.hosts,
      scenario.botCount,
      scenario.botUsername
    ).map((host) => host.remark),
  };
} else {
  throw new Error(`unknown op: ${scenario.op}`);
}
process.stdout.write(JSON.stringify(result));
