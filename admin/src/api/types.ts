import type { components } from "../../../shared/api/schema";

type Schemas = components["schemas"];

export type Card = Schemas["CardOut"];
export type Money = Schemas["Money"];
export type Shop = Schemas["ShopOut"];
export type StaffShop = Schemas["StaffShopOut"];
export type StaffMe = Schemas["StaffMeOut"];
export type Token = Schemas["TokenOut"];
export type Dashboard = Schemas["DashboardOut"];
export type StaffStock = Schemas["StaffStockOut"];
export type StaffStockList = Schemas["StaffStockListOut"];
export type StockArchiveResult = Schemas["StockArchiveResultOut"];
export type StockDeleteResult = Schemas["StockDeleteResultOut"];
export type ReservationSummary = Schemas["ReservationSummaryOut"];
export type Reservation = Schemas["ReservationOut"];
export type StaffReservation = Schemas["StaffReservationOut"];
export type ReservationLine = Schemas["ReservationLineOut"];
export type ReservationStatus = Reservation["status"];
export type SettingsUpdate = Schemas["SettingsUpdateIn"];
export type ScryfallRefresh = Schemas["ScryfallRefreshOut"];
export type StatusUpdate = Schemas["StatusUpdateIn"];
export type CompleteIn = Schemas["CompleteIn"];
export type CompleteLine = Schemas["CompleteLineIn"];
export type StockUpdate = Schemas["StockUpdateIn"];
export type StockAdjust = Schemas["StockAdjustIn"];
export type StockSell = Schemas["StockSellIn"];
export type LoginInput = Schemas["StaffLoginIn"];
export type StockImportReport = Schemas["StockImportReportOut"];
export type StockImportReportWithRates = StockImportReport;
export type ExchangeRate = Schemas["ExchangeRateOut"];
export type StaffUser = Schemas["StaffUserOut"];
export type StaffUserCreate = Schemas["StaffUserCreateIn"];
export type StaffUserUpdate = Schemas["StaffUserUpdateIn"];
export type AuditEvent = Schemas["AuditEventOut"];
export type CardRequest = Schemas["CardRequestOut"];
export type StaffCardRequest = Schemas["StaffCardRequestOut"];
export type QuoteIn = Schemas["QuoteIn"];
export type DeclineIn = Schemas["DeclineIn"];
export type ConvertIn = Schemas["ConvertIn"];
export type StaffNotification = Schemas["StaffNotificationOut"];
export type StaffNotificationList = Schemas["StaffNotificationListOut"];
export type NotificationReadResult = Schemas["NotificationReadResultOut"];

/** Card variant values, derived from the generated request schema. */
export type Finish = Schemas["StockCreateIn"]["finish"];
export type Condition = Schemas["StockCreateIn"]["condition"];

/**
 * Statuses that still hold stock. UI-only copy of the backend
 * RESERVATION_ACTIVE_STATUSES tuple; the API serializes status as a string.
 */
export const ACTIVE_STATUSES = ["REQUESTED", "CONFIRMED", "READY"] as const;

/** Transitions a vendor may make from the queue. Mirrors the staff API. */
export const NEXT_STATUS: Record<string, StatusUpdate["status"][]> = {
  REQUESTED: ["CONFIRMED", "CANCELLED"],
  CONFIRMED: ["READY", "CANCELLED"],
  READY: ["CANCELLED"],
};
