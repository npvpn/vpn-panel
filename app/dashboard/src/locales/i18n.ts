import { joinPaths } from "@remix-run/router";

import fa from "date-fns/locale/fa-IR";
import ru from "date-fns/locale/ru";
import zh from "date-fns/locale/zh-CN";
import dayjs from "dayjs";
import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import HttpApi from "i18next-http-backend";
import { registerLocale } from "react-datepicker";
import { initReactI18next } from "react-i18next";

declare const __I18N_VERSION__: string;

declare module "i18next" {
    interface CustomTypeOptions {
        returnNull: false;
    }
}

i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .use(HttpApi)
    .init(
        {
            debug: import.meta.env.NODE_ENV === "development",
            returnNull: false,
            fallbackLng: "en",
            interpolation: {
                escapeValue: false,
            },
            react: {
                useSuspense: false,
            },
            load: "languageOnly",
            detection: {
                caches: ["localStorage", "sessionStorage", "cookie"],
            },
            backend: {
                loadPath:
                    joinPaths([
                        import.meta.env.BASE_URL,
                        `statics/locales/{{lng}}.json`,
                    ]) + `?v=${__I18N_VERSION__}`,
            },
        },
        function (err, t) {
            dayjs.locale(i18n.language);
        }
    );

i18n.on("languageChanged", (lng) => {
    dayjs.locale(lng);
});

// DataPicker
// Календарю передают i18n.language в нижнем регистре, а детектор отдаёт язык
// браузера с регионом («ru-RU» → «ru-ru»): регистрируем и короткую, и региональную
// форму, иначе календарь падал на английский с предупреждением в консоли.
registerLocale("zh-cn", zh);
registerLocale("zh", zh);
registerLocale("ru", ru);
registerLocale("ru-ru", ru);
registerLocale("fa", fa);
registerLocale("fa-ir", fa);

export default i18n;