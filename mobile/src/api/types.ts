import type { components } from "./schema";

type Schemas = components["schemas"];

export type Shop = Schemas["ShopOut"];
export type Money = Schemas["Money"];
export type Card = Schemas["CardOut"];
export type StockItem = Schemas["StockItemOut"];
export type StockList = Schemas["StockListOut"];
export type Reservation = Schemas["ReservationOut"];
export type ReservationCreate = Schemas["ReservationCreate"];
export type ReservationLine = Schemas["ReservationLineOut"];
export type RestockAlert = Schemas["RestockAlertOut"];
export type RestockAlertCreate = Schemas["RestockAlertCreateIn"];
export type CardRequest = Schemas["CardRequestOut"];
export type CardRequestCreate = Schemas["CardRequestCreateIn"];
export type Customer = Schemas["CustomerIn"];
export type CustomerAccount = Schemas["CustomerOut"];
export type CustomerProfileUpdate = {
  display_name?: string | null;
  phone?: string | null;
  push_notifications_enabled?: boolean | null;
  email_notifications_enabled?: boolean | null;
  quiet_hours_enabled?: boolean | null;
  notifications_opt_out?: boolean | null;
};
export type ClaimedCounts = Schemas["ClaimedOut"];
export type OtpRequestResult = Schemas["OtpRequestOut"];
export type CustomerToken = Schemas["CustomerTokenOut"];
export type AccountReservation = Schemas["MeReservationSummaryOut"];
export type AccountCardRequest = Schemas["MeCardRequestOut"];
export type AccountRestockAlert = Schemas["MeRestockAlertOut"];
export type PushToken = Schemas["PushTokenOut"];
export type PushTokenCreate = Schemas["PushTokenIn"];

export type StockSort = "relevance" | "name" | "price_asc" | "price_desc" | "newest";

export type StockQuery = {
  query?: string;
  sort?: StockSort;
  availableOnly?: boolean;
  cursor?: string | null;
  limit?: number;
};

export type FacetValue = { value: string; count: number };

export type Facets = {
  sets: FacetValue[];
  rarities: FacetValue[];
  finishes: FacetValue[];
  conditions: FacetValue[];
  languages: FacetValue[];
};

export type SavedReservation = Omit<Reservation, "access_token">;

export type CartLine = {
  stockId: string;
  quantity: number;
  item: StockItem;
};
