import { injectionSchema, effectiveInjection, previewHost, previewExcludedIds, previewDraftHosts } from "../../app/dashboard/src/components/hostsDialog/hostInjection.ts";
const input=JSON.parse(process.argv[2]);
console.log(JSON.stringify(input.op === "drafts" ? previewDraftHosts(input.rows, input.complete) : input.op === "excluded" ? previewExcludedIds(input.saved, input.rows, input.complete) : input.op === "preview" ? previewHost(input.host) : input.op === "effective" ? effectiveInjection(input.host,input.templates) : injectionSchema.safeParse(input.value)));
