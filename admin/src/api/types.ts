import type { components } from "./schema";

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
export type ReservationSummary = Schemas["ReservationSummaryOut"];
export type Reservation = Schemas["ReservationOut"];
export type StaffReservation = Schemas["StaffReservationOut"];
export type ReservationLine = Schemas["ReservationLineOut"];
export type ReservationStatus = Reservation["status"];
export type SettingsUpdate = Schemas["SettingsUpdateIn"];
export type StatusUpdate = Schemas["StatusUpdateIn"];
export type CompleteIn = Schemas["CompleteIn"];
export type CompleteLine = Schemas["CompleteLineIn"];
export type StockUpdate = Schemas["StockUpdateIn"];
export type StockAdjust = Schemas["StockAdjustIn"];
export type StockSell = Schemas["StockSellIn"];
export type LoginInput = Schemas["StaffLoginIn"];
export type StockImportReport = Schemas["StockImportReportOut"];

/** Statuses that still hold stock. Mirrors the backend ACTIVE_STATUSES tuple. */
export const ACTIVE_STATUSES = ["REQUESTED", "CONFIRMED", "READY"] as const;

/** Transitions a vendor may make from the queue. */
export const NEXT_STATUS: Record<string, StatusUpdate["status"][]> = {
  REQUESTED: ["CONFIRMED", "READY", "CANCELLED"],
  CONFIRMED: ["READY", "CANCELLED"],
  READY: ["CANCELLED"],
};
