import { useLocale } from "../state/locale";

type Props = {
  onHand: number;
  reserved: number;
  available: number;
};

/**
 * Stock numbers always pair colour with a text label, so the state is readable
 * without colour vision and in print.
 */
export function StockLevels({ onHand, reserved, available }: Props) {
  const { t } = useLocale();
  const state = available <= 0 ? "out" : reserved > 0 ? "held" : "available";
  const stateLabel =
    available <= 0 ? t("Out of stock") : reserved > 0 ? t("Partially held") : t("Available");

  return (
    <div className="stock-levels">
      <span className="stock-levels__state" data-state={state}>
        <span aria-hidden="true" className="dot" />
        {stateLabel}
      </span>
      <dl className="stock-levels__numbers">
        <div>
          <dt>{t("On hand")}</dt>
          <dd>{onHand}</dd>
        </div>
        <div>
          <dt>{t("Reserved")}</dt>
          <dd className="tone--reserved">{reserved}</dd>
        </div>
        <div>
          <dt>{t("Available")}</dt>
          <dd className="tone--available">{available}</dd>
        </div>
      </dl>
    </div>
  );
}
