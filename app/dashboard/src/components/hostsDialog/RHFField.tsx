import { FormControl, FormLabel } from "@chakra-ui/react";
import { Error } from "./constants";

type RHFFieldProps = {
  label: React.ReactNode;
  error?: any;
  isInvalid?: boolean;
  rightElement?: React.ReactNode;
  hideLabel?: boolean;
  formControlProps?: any;
  formLabelProps?: any;
  children: React.ReactNode;
};

export const RHFField = ({
  label,
  error,
  isInvalid,
  rightElement,
  hideLabel,
  formControlProps,
  formLabelProps,
  children,
}: RHFFieldProps) => (
  <FormControl isInvalid={isInvalid ?? !!error} {...formControlProps}>
    {!hideLabel && (
      <FormLabel
        display="flex"
        justifyContent="space-between"
        alignItems="center"
        {...formLabelProps}
      >
        <span>{label}</span>
        {rightElement}
      </FormLabel>
    )}

    {children}

    {error && <Error>{error.message}</Error>}
  </FormControl>
);
