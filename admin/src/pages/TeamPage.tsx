import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { useCreateStaff, useTeam, useUpdateStaff } from "../api/queries";
import type { StaffUser, StaffUserUpdate } from "../api/types";
import { useAuth } from "../auth/context";
import { formatDateTime } from "../lib/format";
import { useLocale } from "../state/locale";
import { usePreferences } from "../state/preferences";

type Role = "staff" | "owner";

export function TeamPage() {
  const { session } = useAuth();
  const { t } = useLocale();
  const isOwner = session?.me.role === "owner";
  const { data, isPending, error } = useTeam(isOwner);

  if (!isOwner) {
    return (
      <div className="page">
        <h1>{t("Team")}</h1>
        <p className="muted">{t("Only the shop owner can manage team members.")}</p>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>{t("Team")}</h1>
          <p className="muted">{t("Give staff their own sign-in instead of sharing the owner password.")}</p>
        </div>
      </header>

      <AddMember />

      <section className="card" aria-labelledby="team-list-title">
        <h2 id="team-list-title">{t("People with access")}</h2>
        {error ? (
          <p className="alert alert--error" role="alert">
            {error instanceof ApiError ? t(error.message) : t("Could not load the team.")}
          </p>
        ) : null}
        {isPending ? <p className="muted">{t("Loading…")}</p> : null}
        {data ? <TeamTable people={data} currentUserId={session?.me.id ?? ""} /> : null}
      </section>
    </div>
  );
}

function AddMember() {
  const { t } = useLocale();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("staff");
  const [notice, setNotice] = useState<string | null>(null);
  const create = useCreateStaff();

  function submit(event: FormEvent) {
    event.preventDefault();
    setNotice(null);
    create.mutate(
      {
        email: email.trim(),
        display_name: displayName.trim() || null,
        password,
        role,
      },
      {
        onSuccess: (person) => {
          setNotice(t("{email} can now sign in.", { email: person.email }));
          setEmail("");
          setDisplayName("");
          setPassword("");
          setRole("staff");
        },
      },
    );
  }

  return (
    <section className="card" aria-labelledby="add-member-title">
      <h2 id="add-member-title">{t("Add a team member")}</h2>
      <form className="inline-form" onSubmit={submit}>
        <label htmlFor="member-email">{t("Email")}</label>
        <input
          id="member-email"
          type="email"
          required
          autoComplete="off"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          data-testid="member-email"
        />

        <label htmlFor="member-name">{t("Name")}</label>
        <input
          id="member-name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          data-testid="member-name"
        />

        <label htmlFor="member-role">{t("Role")}</label>
        <select
          id="member-role"
          value={role}
          onChange={(event) => setRole(event.target.value as Role)}
        >
          <option value="staff">{t("Staff")}</option>
          <option value="owner">{t("Owner")}</option>
        </select>

        <label htmlFor="member-password">{t("Temporary password")}</label>
        <input
          id="member-password"
          type="password"
          required
          minLength={10}
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          data-testid="member-password"
        />
        <p className="muted small">{t("At least 10 characters. Share it with them, then let them change it.")}</p>

        <button type="submit" className="btn btn--primary" disabled={create.isPending} data-testid="member-submit">
          {create.isPending ? t("Adding…") : t("Add member")}
        </button>
      </form>

      {create.error ? (
        <p className="alert alert--error" role="alert">
          {create.error instanceof ApiError ? t(create.error.message) : t("Could not add this person.")}
        </p>
      ) : null}
      {notice ? (
        <p className="alert alert--success" role="status">
          {notice}
        </p>
      ) : null}
    </section>
  );
}

function TeamTable({ people, currentUserId }: { people: StaffUser[]; currentUserId: string }) {
  const { t, locale } = useLocale();
  const { preferences } = usePreferences();
  const [resetting, setResetting] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const update = useUpdateStaff();

  function save(id: string, patch: StaffUserUpdate) {
    setProblem(null);
    setNotice(null);
    update.mutate(
      { id, patch },
      {
        onSuccess: (person) => {
          setNotice(t("Saved {email}.", { email: person.email }));
          setResetting(null);
          setNewPassword("");
        },
        onError: (error) => {
          setProblem(error instanceof ApiError ? t(error.message) : t("Could not save this change."));
        },
      },
    );
  }

  return (
    <>
      {problem ? (
        <p className="alert alert--error" role="alert">
          {problem}
        </p>
      ) : null}
      {notice ? (
        <p className="alert alert--success" role="status">
          {notice}
        </p>
      ) : null}

      <div className="table-wrap">
        <table className="table">
          <caption className="sr-only">{t("Team members and their access")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("Member")}</th>
              <th scope="col">{t("Role")}</th>
              <th scope="col">{t("Status")}</th>
              <th scope="col">{t("Added")}</th>
              <th scope="col">{t("Actions")}</th>
            </tr>
          </thead>
          <tbody>
            {people.map((person) => {
              const isSelf = person.id === currentUserId;
              return (
                <tr key={person.id}>
                  <td>
                    <strong>{person.display_name || person.email}</strong>
                    <br />
                    <span className="muted small">{person.email}</span>
                  </td>
                  <td>{person.role === "owner" ? t("Owner") : t("Staff")}</td>
                  <td>
                    <span className={`badge badge--${person.is_active ? "confirmed" : "offline"}`}>
                      <span aria-hidden="true" className="badge__dot" />
                      {person.is_active ? t("Active") : t("Deactivated")}
                    </span>
                  </td>
                  <td className="nowrap">{formatDateTime(person.created_at, { locale, timeFormat: preferences.timeFormat })}</td>
                  <td>
                    <div className="row-actions">
                      <button
                        type="button"
                        className="btn btn--small"
                        disabled={update.isPending}
                        onClick={() =>
                          save(person.id, { role: person.role === "owner" ? "staff" : "owner" })
                        }
                      >
                        {person.role === "owner" ? t("Make staff") : t("Make owner")}
                      </button>
                      <button
                        type="button"
                        className="btn btn--small"
                        disabled={update.isPending || (isSelf && person.is_active)}
                        title={isSelf && person.is_active ? t("You cannot deactivate your own account") : undefined}
                        onClick={() => save(person.id, { is_active: !person.is_active })}
                      >
                        {person.is_active ? t("Deactivate") : t("Reactivate")}
                      </button>
                      <button
                        type="button"
                        className="btn btn--small"
                        onClick={() => {
                          setResetting(resetting === person.id ? null : person.id);
                          setNewPassword("");
                        }}
                      >
                        {resetting === person.id ? t("Cancel") : t("Reset password")}
                      </button>
                    </div>
                    {resetting === person.id ? (
                      <form
                        className="inline-form inline-form--tight"
                        onSubmit={(event) => {
                          event.preventDefault();
                          save(person.id, { password: newPassword });
                        }}
                      >
                        <label htmlFor={`new-password-${person.id}`}>{t("New password")}</label>
                        <input
                          id={`new-password-${person.id}`}
                          type="password"
                          minLength={10}
                          required
                          autoComplete="new-password"
                          value={newPassword}
                          onChange={(event) => setNewPassword(event.target.value)}
                        />
                        <button type="submit" className="btn btn--small btn--primary" disabled={update.isPending}>
                          {t("Save password")}
                        </button>
                      </form>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
