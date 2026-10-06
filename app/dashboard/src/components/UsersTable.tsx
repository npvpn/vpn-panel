import {
  Accordion,
  AccordionButton,
  AccordionItem,
  AccordionPanel,
  Box,
  Button,
  chakra,
  ExpandedIndex,
  HStack,
  IconButton,
  Select,
  Slider,
  SliderFilledTrack,
  SliderProps,
  SliderTrack,
  Table,
  TableProps,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tooltip,
  Tr,
  useBreakpointValue,
  VStack,
} from "@chakra-ui/react";
import {
  CheckIcon,
  ChevronDownIcon,
  ClipboardIcon,
  LinkIcon,
  PencilIcon,
  QrCodeIcon,
} from "@heroicons/react/24/outline";
import { ReactComponent as AddFileIcon } from "assets/add_file.svg";
import classNames from "classnames";
import { resetStrategy, statusColors } from "constants/UserSettings";
import { useDashboard } from "contexts/DashboardContext";
import { t } from "i18next";
import { FC, Fragment, useEffect, useState } from "react";
import CopyToClipboard from "react-copy-to-clipboard";
import { useTranslation } from "react-i18next";
import { User } from "types/User";
import { formatBytes } from "utils/formatByte";
import { OnlineBadge } from "./OnlineBadge";
import { OnlineStatus } from "./OnlineStatus";
import { Pagination } from "./Pagination";
import { StatusBadge } from "./StatusBadge";

const EmptySectionIcon = chakra(AddFileIcon);

const iconProps = {
  baseStyle: {
    w: {
      base: 4,
      md: 5,
    },
    h: {
      base: 4,
      md: 5,
    },
  },
};
const CopyIcon = chakra(ClipboardIcon, iconProps);
const AccordionArrowIcon = chakra(ChevronDownIcon, iconProps);
const CopiedIcon = chakra(CheckIcon, iconProps);
const SubscriptionLinkIcon = chakra(LinkIcon, iconProps);
const QRIcon = chakra(QrCodeIcon, iconProps);
const EditIcon = chakra(PencilIcon, iconProps);
const SortIcon = chakra(ChevronDownIcon, {
  baseStyle: {
    width: "15px",
    height: "15px",
  },
});
type UsageSliderProps = {
  used: number;
  total: number | null;
  dataLimitResetStrategy: string | null;
  totalUsedTraffic: number;
  label?: string;
  barMaxW?: string;
} & SliderProps;

const getResetStrategy = (strategy: string): string => {
  for (var i = 0; i < resetStrategy.length; i++) {
    const entry = resetStrategy[i];
    if (entry.value == strategy) {
      return entry.title;
    }
  }
  return "No";
};

const hasBsTraffic = (user: User) =>
  user.bs_monthly_limit_total != null && user.bs_monthly_limit_total > 0;

const BsTrafficUsage: FC<{
  user: User;
  compact?: boolean;
  colorScheme?: string;
  showLabel?: boolean;
  barMaxW?: string;
  emptyPlaceholder?: boolean;
}> = ({
  user,
  compact,
  colorScheme = "primary",
  showLabel = true,
  barMaxW,
  emptyPlaceholder = false,
}) => {
  if (!hasBsTraffic(user)) {
    if (!emptyPlaceholder) {
      return null;
    }
    return (
      <Text
        fontSize="xs"
        color="gray.400"
        _dark={{ color: "gray.500" }}
      >
        —
      </Text>
    );
  }
  const used = user.bs_monthly_used ?? 0;
  const total = user.bs_monthly_limit_total ?? 0;
  const props = {
    used,
    total,
    dataLimitResetStrategy: "month" as const,
    totalUsedTraffic: used,
    colorScheme,
    label: showLabel ? t("usersTable.bsDataUsage") : undefined,
    barMaxW,
  };
  return compact ? (
    <UsageSliderCompact {...props} />
  ) : (
    <Box width="full" maxW={barMaxW} minW="160px">
      <UsageSlider {...props} />
    </Box>
  );
};

const UsageSliderCompact: FC<UsageSliderProps> = (props) => {
  const { used, total, dataLimitResetStrategy, totalUsedTraffic, label } = props;
  const isUnlimited = total === 0 || total === null;
  return (
    <HStack
      justifyContent="space-between"
      fontSize="xs"
      fontWeight="medium"
      color="gray.600"
      _dark={{
        color: "gray.400",
      }}
    >
      <Text>
        {label ? (
          <Text as="span" fontWeight="semibold" mr={1}>
            {label}:
          </Text>
        ) : null}
        {formatBytes(used)} /{" "}
        {isUnlimited ? (
          <Text as="span" fontFamily="system-ui">
            ∞
          </Text>
        ) : (
          formatBytes(total)
        )}
      </Text>
    </HStack>
  );
};
const UsageSlider: FC<UsageSliderProps> = (props) => {
  const {
    used,
    total,
    dataLimitResetStrategy,
    totalUsedTraffic,
    label,
    barMaxW,
    ...restOfProps
  } = props;
  const isUnlimited = total === 0 || total === null;
  const isReached = !isUnlimited && (used / total) * 100 >= 100;
  return (
    <>
      <Box maxW={barMaxW} width="full">
        <Slider
          orientation="horizontal"
          value={isUnlimited ? 100 : Math.min((used / total) * 100, 100)}
          colorScheme={isReached ? "red" : "primary"}
          {...restOfProps}
        >
          <SliderTrack h="5px" borderRadius="full">
            <SliderFilledTrack borderRadius="full" />
          </SliderTrack>
        </Slider>
      </Box>
      <HStack
        justifyContent="space-between"
        fontSize="xs"
        fontWeight="medium"
        color="gray.600"
        _dark={{
          color: "gray.400",
        }}
      >
        <Text>
          {label ? (
            <Text as="span" fontWeight="semibold" mr={1}>
              {label}:
            </Text>
          ) : null}
          {formatBytes(used)} /{" "}
          {isUnlimited ? (
            <Text as="span" fontFamily="system-ui">
              ∞
            </Text>
          ) : (
            formatBytes(total) +
            (dataLimitResetStrategy && dataLimitResetStrategy !== "no_reset"
              ? " " +
                t(
                  "userDialog.resetStrategy" +
                    getResetStrategy(dataLimitResetStrategy)
                )
              : "")
          )}
        </Text>
        <Text>
          {t("usersTable.total")}: {formatBytes(totalUsedTraffic)}
        </Text>
      </HStack>
    </>
  );
};
export type SortType = {
  sort: string;
  column: string;
};
export const Sort: FC<SortType> = ({ sort, column }) => {
  if (sort.includes(column))
    return (
      <SortIcon
        transform={sort.startsWith("-") ? undefined : "rotate(180deg)"}
      />
    );
  return null;
};
type UsersTableProps = {} & TableProps;
export const UsersTable: FC<UsersTableProps> = (props) => {
  const {
    filters,
    users: { users },
    onEditingUser,
    onFilterChange,
  } = useDashboard();

  const { t } = useTranslation();
  const [selectedRow, setSelectedRow] = useState<ExpandedIndex | undefined>(
    undefined
  );
  const marginTop = useBreakpointValue({ base: 120, lg: 72 }) || 72;
  const [top, setTop] = useState(`${marginTop}px`);
  const useTable = useBreakpointValue({ base: false, md: true });

  useEffect(() => {
    const calcTop = () => {
      const el = document.querySelectorAll("#filters")[0] as HTMLElement;
      setTop(`${el.offsetHeight}px`);
    };
    window.addEventListener("scroll", calcTop);
    () => window.removeEventListener("scroll", calcTop);
  }, []);

  // total с бэкенда уже учитывает фильтры: при пустой выдаче он тоже 0, поэтому
  // «отфильтровано ли» смотрим по самим фильтрам, а не по сравнению счётчиков.
  const isFiltered = Boolean(
    filters.search || filters.status || filters.bot_username
  );

  const handleSort = (column: string) => {
    let newSort = filters.sort;
    if (newSort.includes(column)) {
      if (newSort.startsWith("-")) {
        newSort = "-created_at";
      } else {
        newSort = "-" + column;
      }
    } else {
      newSort = column;
    }
    onFilterChange({
      sort: newSort,
    });
  };
  const handleStatusFilter = (e: any) => {
    onFilterChange({
      status: e.target.value.length > 0 ? e.target.value : undefined,
    });
  };

  const toggleAccordion = (index: number) => {
    setSelectedRow(index === selectedRow ? undefined : index);
  };

  return (
    <Box id="users-table" overflowX={{ base: "unset", md: "unset" }}>
      <Accordion
        allowMultiple
        display={{ base: "block", md: "none" }}
        index={selectedRow}
      >
        {/* Пять колонок на ~345px экрана: фиксированная раскладка с узкими колонками
            цифр, имя пользователя забирает остаток ширины и обрезается многоточием.
            Заголовкам — мелкий шрифт без разрядки, иначе они не влезают в колонки. */}
        <Table
          orientation="vertical"
          zIndex="docked"
          w="full"
          sx={{
            tableLayout: "fixed",
            "& th": { fontSize: "10px", letterSpacing: "normal" },
          }}
          {...props}
        >
          <Thead zIndex="docked" position="relative">
            <Tr>
              <Th
                position="sticky"
                top={top}
                pl={3}
                pr={1}
                cursor={"pointer"}
                onClick={handleSort.bind(null, "username")}
              >
                <HStack>
                  <span>{t("users")}</span>
                  <Sort sort={filters.sort} column="username" />
                </HStack>
              </Th>
              <Th
                position="sticky"
                top={top}
                pl={0}
                pr={0}
                w="56px"
                cursor={"pointer"}
              >
                <HStack spacing={0} position="relative">
                  <Text
                    position="absolute"
                    _dark={{
                      bg: "gray.750",
                    }}
                    _light={{
                      bg: "#F9FAFB",
                    }}
                    userSelect="none"
                    pointerEvents="none"
                    zIndex={1}
                    w="100%"
                    isTruncated
                  >
                    {t("usersTable.status")}
                    {filters.status ? ": " + filters.status : ""}
                  </Text>
                  <Select
                    value={filters.sort}
                    fontSize="xs"
                    fontWeight="extrabold"
                    textTransform="uppercase"
                    cursor="pointer"
                    p={0}
                    border={0}
                    h="auto"
                    w="auto"
                    icon={<></>}
                    _focusVisible={{
                      border: "0 !important",
                    }}
                    onChange={handleStatusFilter}
                  >
                    <option></option>
                    <option>active</option>
                    <option>on_hold</option>
                    <option>disabled</option>
                    <option>limited</option>
                    <option>expired</option>
                  </Select>
                </HStack>
              </Th>
              <Th
                position="sticky"
                top={top}
                w="72px"
                cursor={"pointer"}
                pl={2}
                pr={0}
                onClick={handleSort.bind(null, "used_traffic")}
              >
                <HStack>
                  <span>{t("usersTable.dataUsage")}</span>
                  <Sort sort={filters.sort} column="used_traffic" />
                </HStack>
              </Th>
              <Th position="sticky" top={top} w="72px" pl={2} pr={1}>
                <span>{t("usersTable.bsDataUsage")}</span>
              </Th>
              <Th
                position="sticky"
                top={top}
                w="24px"
                p={0}
                cursor={"pointer"}
              ></Th>
            </Tr>
          </Thead>
          <Tbody>
            {!useTable &&
              users?.map((user, i) => {
                return (
                  <Fragment key={user.username}>
                    <Tr
                      onClick={toggleAccordion.bind(null, i)}
                      cursor="pointer"
                    >
                      <Td borderBottom={0} pl={3} pr={1}>
                        <HStack spacing={2} minW={0}>
                          <Box flexShrink={0}>
                            <OnlineBadge lastOnline={user.online_at} />
                          </Box>
                          <Text isTruncated minW={0}>
                            {user.username}
                          </Text>
                        </HStack>
                      </Td>
                      <Td borderBottom={0} pl={0} pr={0}>
                        <StatusBadge
                          compact
                          showDetail={false}
                          expiryDate={user.expire}
                          status={user.status}
                        />
                      </Td>
                      <Td borderBottom={0} pl={2} pr={0}>
                        <UsageSliderCompact
                          totalUsedTraffic={user.lifetime_used_traffic}
                          dataLimitResetStrategy={
                            user.data_limit_reset_strategy
                          }
                          used={user.used_traffic}
                          total={user.data_limit}
                          colorScheme={statusColors[user.status].bandWidthColor}
                        />
                      </Td>
                      <Td borderBottom={0} pl={2} pr={1}>
                        <BsTrafficUsage
                          user={user}
                          compact
                          showLabel={false}
                          colorScheme={statusColors[user.status].bandWidthColor}
                          emptyPlaceholder
                        />
                      </Td>
                      <Td p={0} borderBottom={0}>
                        <AccordionArrowIcon
                          color="gray.600"
                          _dark={{
                            color: "gray.400",
                          }}
                          transition="transform .2s ease-out"
                          transform={
                            selectedRow === i ? "rotate(180deg)" : "0deg"
                          }
                        />
                      </Td>
                    </Tr>
                    <Tr
                      className="collapsible"
                      onClick={toggleAccordion.bind(null, i)}
                    >
                      <Td p={0} colSpan={5}>
                        <AccordionItem border={0}>
                          <AccordionButton display="none"></AccordionButton>
                          <AccordionPanel
                            border={0}
                            cursor="pointer"
                            px={6}
                            py={3}
                          >
                            <VStack justifyContent="space-between" spacing="4">
                              <VStack
                                alignItems="flex-start"
                                w="full"
                                spacing={-1}
                              >
                                <Text
                                  textTransform="capitalize"
                                  fontSize="xs"
                                  fontWeight="bold"
                                  color="gray.600"
                                  _dark={{
                                    color: "gray.400",
                                  }}
                                >
                                  {t("usersTable.dataUsage")}
                                </Text>
                                <Box width="full" maxW="280px">
                                  <UsageSlider
                                    totalUsedTraffic={
                                      user.lifetime_used_traffic
                                    }
                                    dataLimitResetStrategy={
                                      user.data_limit_reset_strategy
                                    }
                                    used={user.used_traffic}
                                    total={user.data_limit}
                                    colorScheme={
                                      statusColors[user.status].bandWidthColor
                                    }
                                    barMaxW="280px"
                                  />
                                </Box>
                              </VStack>
                              {hasBsTraffic(user) && (
                                <VStack
                                  alignItems="flex-start"
                                  w="full"
                                  spacing={-1}
                                >
                                  <Text
                                    textTransform="capitalize"
                                    fontSize="xs"
                                    fontWeight="bold"
                                    color="gray.600"
                                    _dark={{
                                      color: "gray.400",
                                    }}
                                  >
                                    {t("usersTable.bsDataUsage")}
                                  </Text>
                                  <BsTrafficUsage
                                    user={user}
                                    barMaxW="280px"
                                    colorScheme={
                                      statusColors[user.status].bandWidthColor
                                    }
                                  />
                                </VStack>
                              )}
                              <HStack w="full" justifyContent="space-between">
                                <Box width="full">
                                  <StatusBadge
                                    compact
                                    expiryDate={user.expire}
                                    status={user.status}
                                  />
                                  <OnlineStatus lastOnline={user.online_at} />
                                </Box>
                                <HStack>
                                  <ActionButtons user={user} />
                                  <Tooltip
                                    label={t("userDialog.editUser")}
                                    placement="top"
                                  >
                                    <IconButton
                                      p="0 !important"
                                      aria-label="Edit user"
                                      bg="transparent"
                                      _dark={{
                                        _hover: {
                                          bg: "gray.700",
                                        },
                                      }}
                                      size={{
                                        base: "sm",
                                        md: "md",
                                      }}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        onEditingUser(user);
                                      }}
                                    >
                                      <EditIcon />
                                    </IconButton>
                                  </Tooltip>
                                </HStack>
                              </HStack>
                            </VStack>
                          </AccordionPanel>
                        </AccordionItem>
                      </Td>
                    </Tr>
                  </Fragment>
                );
              })}
            {!useTable && users.length == 0 && (
              <Tr>
                <Td colSpan={5}>
                  <EmptySection isFiltered={isFiltered} />
                </Td>
              </Tr>
            )}
          </Tbody>
        </Table>
      </Accordion>
      <Table
        orientation="vertical"
        display={{ base: "none", md: "table" }}
        {...props}
      >
        <Thead zIndex="docked" position="relative">
          <Tr>
            <Th
              position="sticky"
              top={{ base: "unset", md: top }}
              minW="140px"
              cursor={"pointer"}
              onClick={handleSort.bind(null, "username")}
            >
              <HStack>
                <span>{t("username")}</span>
                <Sort sort={filters.sort} column="username" />
              </HStack>
            </Th>
            <Th
              position="sticky"
              top={{ base: "unset", md: top }}
              width="280px"
              minW="200px"
              maxW="300px"
              cursor={"pointer"}
            >
              <HStack position="relative" gap={"5px"}>
                <Text
                  _dark={{
                    bg: "gray.750",
                  }}
                  _light={{
                    bg: "#F9FAFB",
                  }}
                  userSelect="none"
                  pointerEvents="none"
                  zIndex={1}
                >
                  {t("usersTable.status")}
                  {filters.status ? ": " + filters.status : ""}
                </Text>
                <Text>/</Text>
                <Sort sort={filters.sort} column="expire" />
                <HStack onClick={handleSort.bind(null, "expire")}>
                  <Text>Sort by expire</Text>
                </HStack>
                <Select
                  fontSize="xs"
                  fontWeight="extrabold"
                  textTransform="uppercase"
                  cursor="pointer"
                  position={"absolute"}
                  p={0}
                  left={"-40px"}
                  border={0}
                  h="auto"
                  w="auto"
                  icon={<></>}
                  _focusVisible={{
                    border: "0 !important",
                  }}
                  value={filters.sort}
                  onChange={handleStatusFilter}
                >
                  <option></option>
                  <option>active</option>
                  <option>on_hold</option>
                  <option>disabled</option>
                  <option>limited</option>
                  <option>expired</option>
                </Select>
              </HStack>
            </Th>
            <Th
              position="sticky"
              top={{ base: "unset", md: top }}
              width="240px"
              minW="200px"
              maxW="260px"
              cursor={"pointer"}
              onClick={handleSort.bind(null, "used_traffic")}
            >
              <HStack>
                <span>{t("usersTable.dataUsage")}</span>
                <Sort sort={filters.sort} column="used_traffic" />
              </HStack>
            </Th>
            <Th
              position="sticky"
              top={{ base: "unset", md: top }}
              width="200px"
              minW="180px"
              maxW="220px"
            >
              <span>{t("usersTable.bsDataUsage")}</span>
            </Th>
            <Th
              position="sticky"
              top={{ base: "unset", md: top }}
              width="200px"
              minW="180px"
            />
          </Tr>
        </Thead>
        <Tbody>
          {useTable &&
            users?.map((user, i) => {
              return (
                <Tr
                  key={user.username}
                  className={classNames("interactive", {
                    "last-row": i === users.length - 1,
                  })}
                  onClick={() => onEditingUser(user)}
                >
                  <Td minW="140px">
                    <div className="flex-status">
                      <OnlineBadge lastOnline={user.online_at} />
                      {user.username}
                      <OnlineStatus lastOnline={user.online_at} />
                    </div>
                  </Td>
                  <Td width="280px" minW="200px" maxW="300px">
                    <StatusBadge
                      expiryDate={user.expire}
                      status={user.status}
                    />
                  </Td>
                  <Td width="240px" minW="200px" maxW="260px">
                    <UsageSlider
                      totalUsedTraffic={user.lifetime_used_traffic}
                      dataLimitResetStrategy={user.data_limit_reset_strategy}
                      used={user.used_traffic}
                      total={user.data_limit}
                      colorScheme={statusColors[user.status].bandWidthColor}
                      barMaxW="220px"
                    />
                  </Td>
                  <Td width="200px" minW="180px" maxW="220px">
                    <BsTrafficUsage
                      user={user}
                      showLabel={false}
                      barMaxW="200px"
                      colorScheme={statusColors[user.status].bandWidthColor}
                      emptyPlaceholder
                    />
                  </Td>
                  <Td width="200px" minW="180px">
                    <ActionButtons user={user} />
                  </Td>
                </Tr>
              );
            })}
          {users.length == 0 && (
            <Tr>
              <Td colSpan={5}>
                <EmptySection isFiltered={isFiltered} />
              </Td>
            </Tr>
          )}
        </Tbody>
      </Table>
      <Pagination />
    </Box>
  );
};

type ActionButtonsProps = {
  user: User;
};

const ActionButtons: FC<ActionButtonsProps> = ({ user }) => {
  const { setQRCode, setSubLink } = useDashboard();

  const proxyLinks = user.links.join("\r\n");

  const [copied, setCopied] = useState([-1, false]);
  useEffect(() => {
    if (copied[1]) {
      setTimeout(() => {
        setCopied([-1, false]);
      }, 1000);
    }
  }, [copied]);
  return (
    <HStack
      justifyContent="flex-end"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      <CopyToClipboard
        text={
          user.subscription_url.startsWith("/")
            ? window.location.origin + user.subscription_url
            : user.subscription_url
        }
        onCopy={() => {
          setCopied([0, true]);
        }}
      >
        <div>
          <Tooltip
            label={
              copied[0] == 0 && copied[1]
                ? t("usersTable.copied")
                : t("usersTable.copyLink")
            }
            placement="top"
          >
            <IconButton
              p="0 !important"
              aria-label="copy subscription link"
              bg="transparent"
              _dark={{
                _hover: {
                  bg: "gray.700",
                },
              }}
              size={{
                base: "sm",
                md: "md",
              }}
            >
              {copied[0] == 0 && copied[1] ? (
                <CopiedIcon />
              ) : (
                <SubscriptionLinkIcon />
              )}
            </IconButton>
          </Tooltip>
        </div>
      </CopyToClipboard>
      <CopyToClipboard
        text={proxyLinks}
        onCopy={() => {
          setCopied([1, true]);
        }}
      >
        <div>
          <Tooltip
            label={
              copied[0] == 1 && copied[1]
                ? t("usersTable.copied")
                : t("usersTable.copyConfigs")
            }
            placement="top"
          >
            <IconButton
              p="0 !important"
              aria-label="copy configs"
              bg="transparent"
              _dark={{
                _hover: {
                  bg: "gray.700",
                },
              }}
              size={{
                base: "sm",
                md: "md",
              }}
            >
              {copied[0] == 1 && copied[1] ? <CopiedIcon /> : <CopyIcon />}
            </IconButton>
          </Tooltip>
        </div>
      </CopyToClipboard>
      <Tooltip label="QR Code" placement="top">
        <IconButton
          p="0 !important"
          aria-label="qr code"
          bg="transparent"
          _dark={{
            _hover: {
              bg: "gray.700",
            },
          }}
          size={{
            base: "sm",
            md: "md",
          }}
          onClick={() => {
            setQRCode(user.links);
            setSubLink(user.subscription_url);
          }}
        >
          <QRIcon />
        </IconButton>
      </Tooltip>
    </HStack>
  );
};

type EmptySectionProps = {
  isFiltered: boolean;
};

const EmptySection: FC<EmptySectionProps> = ({ isFiltered }) => {
  const { onCreateUser } = useDashboard();
  return (
    <Box
      padding={{ base: 3, md: 5 }}
      py={{ base: 6, md: 8 }}
      display="flex"
      alignItems="center"
      flexDirection="column"
      gap={{ base: 3, md: 4 }}
      w="full"
    >
      <EmptySectionIcon
        maxHeight={{ base: "96px", md: "200px" }}
        maxWidth={{ base: "96px", md: "200px" }}
        _dark={{
          'path[fill="#fff"]': {
            fill: "gray.800",
          },
          'path[fill="#f2f2f2"], path[fill="#e6e6e6"], path[fill="#ccc"]': {
            fill: "gray.700",
          },
          'circle[fill="#3182CE"]': {
            fill: "primary.300",
          },
        }}
        _light={{
          'path[fill="#f2f2f2"], path[fill="#e6e6e6"], path[fill="#ccc"]': {
            fill: "gray.300",
          },
          'circle[fill="#3182CE"]': {
            fill: "primary.500",
          },
        }}
      />
      <Text
        fontWeight="medium"
        fontSize={{ base: "sm", md: "md" }}
        textAlign="center"
        color="gray.600"
        _dark={{ color: "gray.400" }}
      >
        {isFiltered ? t("usersTable.noUserMatched") : t("usersTable.noUser")}
      </Text>
      {!isFiltered && (
        <Button
          size="sm"
          colorScheme="primary"
          onClick={() => onCreateUser(true)}
        >
          {t("createUser")}
        </Button>
      )}
    </Box>
  );
};
