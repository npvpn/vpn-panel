import fs from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import { balancingDefaults, balancingSchema, hasActiveEntryNodes } from "../../app/dashboard/src/components/hostsDialog/hostBalancing.ts";

// schema.tsx — TypeScript без JSX. data:text/javascript Node выполняет как
// обычный JS, поэтому типы снимает stripTypeScriptTypes до сборки URL.
const schemaUrl = new URL("../../app/dashboard/src/components/hostsDialog/schema.tsx", import.meta.url);
const zodUrl = new URL("../../app/dashboard/node_modules/zod/lib/index.mjs", import.meta.url);
const balancingUrl = new URL("../../app/dashboard/src/components/hostsDialog/hostBalancing.ts", import.meta.url);
const injectionUrl = new URL("../../app/dashboard/src/components/hostsDialog/hostInjection.ts", import.meta.url);
const source = stripTypeScriptTypes(
  fs
    .readFileSync(schemaUrl, "utf8")
    .replace('"zod"', JSON.stringify(zodUrl.href))
    .replace('"./hostBalancing"', JSON.stringify(balancingUrl.href))
    .replace('"./hostInjection"', JSON.stringify(injectionUrl.href))
);
const { hostItemSchema } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const input = JSON.parse(process.argv[2]);
if (input.op === "pool") console.log(JSON.stringify(hasActiveEntryNodes(input.ids, input.nodes)));
else if (input.op === "default") console.log(JSON.stringify(balancingSchema.parse(balancingDefaults(input.strategy))));
else if (input.op === "host") console.log(JSON.stringify(hostItemSchema.safeParse(input.host)));
else console.log(JSON.stringify(balancingSchema.safeParse(input.balancing)));
