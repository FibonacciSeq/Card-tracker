"""Create a local demo tenant, owner, cards, and stock."""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Card, Stock, Tenant, TenantSettings, User
from app.security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", default="bolt-shop")
    parser.add_argument("--name", default="Bolt Shop")
    parser.add_argument("--email", default="owner@example.com")
    parser.add_argument("--password", default="secret-password")
    parser.add_argument("--currency", default="RSD")
    args = parser.parse_args()

    with SessionLocal() as db:
        existing = db.scalar(select(Tenant).where(Tenant.slug == args.slug))
        if existing is not None:
            print(f"Tenant '{args.slug}' already exists (id={existing.id})")
            return

        tenant = Tenant(
            slug=args.slug,
            name=args.name,
            currency=args.currency,
            locale="en",
            status="active",
        )
        tenant.settings = TenantSettings(
            brand_name=args.name,
            hold_hours=24,
            directory_opt_in=True,
            payment_instructions="Pay in store when collecting.",
            contact={"email": args.email},
        )
        db.add(tenant)
        db.flush()

        owner = User(
            tenant_id=tenant.id,
            email=args.email,
            password_hash=hash_password(args.password),
            role="owner",
            display_name="Owner",
        )
        db.add(owner)

        samples = [
            (
                "demo-lightning-bolt",
                "Lightning Bolt",
                "LEB",
                "Limited Edition Beta",
                "161",
                "common",
                "Instant",
                ["R"],
                125000,
            ),
            (
                "demo-counterspell",
                "Counterspell",
                "LEB",
                "Limited Edition Beta",
                "60",
                "common",
                "Instant",
                ["U"],
                90000,
            ),
            (
                "demo-black-lotus",
                "Black Lotus",
                "LEA",
                "Limited Edition Alpha",
                "232",
                "rare",
                "Artifact",
                [],
                95000000,
            ),
        ]
        for provider_id, name, set_code, set_name, number, rarity, type_line, colors, price in samples:
            card = Card(
                provider_card_id=provider_id,
                name=name,
                set_code=set_code,
                set_name=set_name,
                collector_number=number,
                rarity=rarity,
                type_line=type_line,
                colors=colors,
            )
            db.add(card)
            db.flush()
            db.add(
                Stock(
                    tenant_id=tenant.id,
                    card_id=card.id,
                    finish="nonfoil",
                    condition="NM",
                    language="en",
                    quantity=3,
                    price_minor=price,
                    currency=args.currency,
                    is_online=True,
                )
            )

        db.commit()
        print(f"Created tenant '{tenant.slug}' (id={tenant.id})")
        print(f"Owner login: {args.email} / {args.password}")
        print("Run the API and open /docs to try the endpoints.")


if __name__ == "__main__":
    main()
