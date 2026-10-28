import { Textarea, TextareaProps } from "@chakra-ui/react";
import { useEffect, useLayoutEffect, useRef } from "react";

// Поле растёт по высоте текста: длинные тексты читаются целиком, без второй
// полосы прокрутки внутри прокручиваемого окна
export const AutoResizeTextarea = (props: TextareaProps) => {
  const ref = useRef<HTMLTextAreaElement>(null);

  const fit = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    // scrollHeight без рамок, а у поля box-sizing: border-box
    el.style.height = `${
      el.scrollHeight + el.offsetHeight - el.clientHeight
    }px`;
  };

  useLayoutEffect(fit, [props.value]);

  // Поле на скрытой вкладке не имеет размера: пересчитываем, когда вкладку
  // открыли или поменялась ширина окна
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth === width) return;
      width = el.clientWidth;
      fit();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <Textarea ref={ref} rows={2} resize="none" overflow="hidden" {...props} />
  );
};
