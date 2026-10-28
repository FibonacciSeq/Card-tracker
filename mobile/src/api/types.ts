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
