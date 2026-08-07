import {
  BoxProps,
  Button,
  chakra,
  FormControl,
  Grid,
  GridItem,
  HStack,
  IconButton,
  Input,
  InputGroup,
  InputLeftElement,
  InputRightElement,
  Spinner,
} from "@chakra-ui/react";
import { StylesConfig } from "react-select";
import {
  ArrowPathIcon,
  MagnifyingGlassIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import classNames from "classnames";
import { useDashboard } from "contexts/DashboardContext";
import debounce from "lodash.debounce";
import React, { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactSelect from "react-select";
import { fetch } from "service/http";
import { Bot } from "types/Bot";
import { useBotSelectStyles } from "hooks/useBotSelectStyles";

const iconProps = {
  baseStyle: {
    w: 4,
    h: 4,
  },
};

const SearchIcon = chakra(MagnifyingGlassIcon, iconProps);
const ClearIcon = chakra(XMarkIcon, iconProps);
export const ReloadIcon = chakra(ArrowPathIcon, iconProps);

export type FilterProps = {} & BoxProps;
const setSearchField = debounce((search: string) => {
  useDashboard.getState().onFilterChange({
    ...useDashboard.getState().filters,
    offset: 0,
    search,
  });
}, 300);

interface BotOption {
  value: number;
  label: string;
}

export const Filters: FC<FilterProps> = ({ ...props }) => {
  const botSelectStyles = useBotSelectStyles({ variant: "filter" });

  const {
    loading,
    filters,
    onFilterChange,
    refetchUsers,
    onCreateUser,
    onConfirmingSyncInbounds,
    isSyncingInbounds,
    syncStatus,
  } = useDashboard();
  const { t } = useTranslation();
  const [search, setSearch] = useState(
    useDashboard.getState().filters.search || ""
  );
  const [bots, setBots] = useState<Bot[]>([]);
  const [selectedBotId, setSelectedBotId] = useState<number | null>(null);

  const botOptions = useMemo<BotOption[]>(
    () =>
      bots.map((bot) => ({
        value: bot.id,
        label: `@${bot.username}`,
      })),
    [bots]
  );

  const selectedOption = useMemo(
    () => botOptions.find((o) => o.value === selectedBotId) ?? null,
    [botOptions, selectedBotId]
  );

  const handleBotChange = (option: BotOption | null) => {
    const botId = option?.value ?? null;
    setSelectedBotId(botId);
    onFilterChange({
      ...filters,
      offset: 0,
      bot_username: option?.label.replace("@", "") || undefined,
    });
  };

  useEffect(() => {
    fetch<Bot[]>("/bots")
      .then(setBots)
      .catch(() => setBots([]));
  }, []);
  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearch(e.target.value);
    setSearchField(e.target.value);
  };
  const clear = () => {
    setSearch("");
    onFilterChange({
      ...filters,
      offset: 0,
      search: "",
    });
  };
  return (
    <Grid
      id="filters"
      templateColumns={{
        lg: "repeat(3, 1fr)",
        md: "repeat(4, 1fr)",
        base: "repeat(1, 1fr)",
      }}
      position="sticky"
      top={0}
      mx="-6"
      px="6"
      rowGap={4}
      gap={{
        lg: 4,
        base: 0,
      }}
      bg="var(--chakra-colors-chakra-body-bg)"
      py={4}
      zIndex="docked"
      {...props}
    >
      <GridItem colSpan={{ base: 1, md: 2, lg: 1 }} order={{ base: 2, md: 1 }}>
        <InputGroup>
          <InputLeftElement pointerEvents="none" children={<SearchIcon />} />
          <Input
            placeholder={t("search")}
            value={search}
            borderColor="light-border"
            onChange={onChange}
          />

          <InputRightElement>
            {loading && <Spinner size="xs" />}
            {filters.search && filters.search.length > 0 && (
              <IconButton
                onClick={clear}
                aria-label="clear"
                size="xs"
                variant="ghost"
              >
                <ClearIcon />
              </IconButton>
            )}
          </InputRightElement>
        </InputGroup>
      </GridItem>
      <GridItem colSpan={2} order={{ base: 1, md: 2 }}>
        <HStack justifyContent="flex-end" alignItems="center" h="full">
          <FormControl w="220px" flexShrink={0}>
            <ReactSelect<BotOption>
              options={botOptions}
              value={selectedOption}
              onChange={handleBotChange}
              placeholder={t("botSettings.selectBot")}
              noOptionsMessage={() => t("botSettings.noBotsFound")}
              isSearchable
              isClearable
              styles={botSelectStyles}
              menuPortalTarget={document.body}
              menuPosition="fixed"
            />
          </FormControl>
          <IconButton
            aria-label="refresh users"
            disabled={loading}
            onClick={refetchUsers}
            variant="outline"
            h="40px"
            w="40px"
            minW="40px"
          >
            <ReloadIcon
              className={classNames({
                "animate-spin": loading,
              })}
            />
          </IconButton>
          <Button
            variant="outline"
            h="40px"
            px={4}
            isLoading={isSyncingInbounds}
            onClick={() => onConfirmingSyncInbounds(true)}
          >
            {t("syncInbounds")}
          </Button>
          {syncStatus && (
            <HStack spacing={2}>
              {syncStatus.running ? (
                <>
                  <Spinner size="xs" />
                  <chakra.span fontSize="sm" color="gray.500">
                    {t("sync.progress", {
                      done: syncStatus.done,
                      total: syncStatus.total || syncStatus.scheduled || 0,
                    })}
                  </chakra.span>
                </>
              ) : (
                <chakra.span fontSize="sm" color="green.500">
                  {t("sync.completed", {
                    done: syncStatus.done,
                    total: syncStatus.total || syncStatus.scheduled || 0,
                  })}
                </chakra.span>
              )}
            </HStack>
          )}
          <Button
            colorScheme="primary"
            h="40px"
            px={5}
            onClick={() => onCreateUser(true)}
          >
            {t("createUser")}
          </Button>
        </HStack>
      </GridItem>
    </Grid>
  );
};
