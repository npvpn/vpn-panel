import { Checkbox, FormControl, FormLabel } from "@chakra-ui/react";
import { useTranslation } from "react-i18next";
import { Error } from "./constants";

export const RHFCheckbox = ({
  label,
  registerProps,
  error,
  formControlProps,
}: any) => {
  const { t } = useTranslation();
  return (
    <FormControl isInvalid={!!error} {...formControlProps}>
      <Checkbox {...registerProps}>{label}</Checkbox>
      {error && <Error>{t(error.message)}</Error>}
    </FormControl>
  );
};
