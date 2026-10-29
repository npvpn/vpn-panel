// Тонкая полоса прокрутки для прокручиваемых окон и списков: стандартная
// широкая выглядит грубо внутри модалок
export const thinScrollbarSx = {
  "&::-webkit-scrollbar": {
    width: "6px",
  },
  "&::-webkit-scrollbar-track": {
    background: "transparent",
  },
  "&::-webkit-scrollbar-thumb": {
    background: "var(--chakra-colors-gray-300)",
    borderRadius: "full",
  },
  "&::-webkit-scrollbar-thumb:hover": {
    background: "var(--chakra-colors-gray-400)",
  },
  scrollbarWidth: "thin",
  scrollbarColor: "var(--chakra-colors-gray-300) transparent",
} as const;
