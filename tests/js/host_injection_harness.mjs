import { injectionSchema, effectiveInjection } from "../../app/dashboard/src/components/hostsDialog/hostInjection.ts";
const input=JSON.parse(process.argv[2]);
console.log(JSON.stringify(input.op === "effective" ? effectiveInjection(input.host,input.templates) : injectionSchema.safeParse(input.value)));
