import { InputGroup } from "@chakra-ui/react";
import { HostsInput } from "./HostsInput";
import { RHFField } from "./RHFField";

type RHFInputProps = {
  label: React.ReactNode;
  error?: any;
  isInvalid?: boolean;
  registerProps: any;
  placeholder?: string;
  type?: string;

  rightElement?: React.ReactNode;
  hideLabel?: boolean;

  formControlProps?: any;
  formLabelProps?: any;
  inputProps?: any;
};

export const RHFInput = ({
  registerProps,
  placeholder,
  type,
  inputProps,
  hideLabel,
  rightElement,
  ...props
}: RHFInputProps) => (
  <RHFField
    {...props}
    hideLabel={hideLabel}
    rightElement={hideLabel ? undefined : rightElement}
  >
    <InputGroup>
      <HostsInput
        {...registerProps}
        {...inputProps}
        placeholder={placeholder}
        type={type}
        endAdornment={hideLabel ? rightElement : inputProps?.endAdornment}
      />
    </InputGroup>
  </RHFField>
);
