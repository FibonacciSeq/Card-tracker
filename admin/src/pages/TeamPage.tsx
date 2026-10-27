import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { useCreateStaff, useTeam, useUpdateStaff } from "../api/queries";
import type { StaffUser, StaffUserUpdate } from "../api/types";
import { useAuth } from "../auth/context";
import { formatDateTime } from "../lib/format";

type Role = "staff" | "owner";

export function TeamPage() {
  const { session } = useAuth();
  const isOwner = session?.me.role === "owner";
  const { data, isPending, error } = useTeam(isOwner);

  if (!isOwner) {
    return (
      <div className="page">
        <h1>Team</h1>
        <p className="muted">Only the shop owner can manage team members.</p>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Team</h1>
          <p className="muted">Give staff their own sign-in instead of sharing the owner password.</p>
        </div>
      </header>

      <AddMember />

      <section className="card" aria-labelledby="team-list-title">
        <h2 id="team-list-title">People with access</h2>
        {error ? (
          <p className="alert alert--error" role="alert">
            {error instanceof ApiError ? error.message : "Could not load the team."}
          </p>
        ) : null}
        {isPending ? <p className="muted">Loading…</p> : null}
        {data ? <TeamTable people={data} currentUserId={session?.me.id ?? ""} /> : null}
      </section>
    </div>
  );
}

function AddMember() {
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
          setNotice(`${person.email} can now sign in.`);
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
      <h2 id="add-member-title">Add a team member</h2>
      <form className="inline-form" onSubmit={submit}>
        <label htmlFor="member-email">Email</label>
        <input
          id="member-email"
          type="email"
          required
          autoComplete="off"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          data-testid="member-email"
        />

        <label htmlFor="member-name">Name</label>
        <input
          id="member-name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          data-testid="member-name"
        />

        <label htmlFor="member-role">Role</label>
        <select
          id="member-role"
          value={role}
          onChange={(event) => setRole(event.target.value as Role)}
        >
          <option value="staff">Staff</option>
          <option value="owner">Owner</option>
        </select>

        <label htmlFor="member-password">Temporary password</label>
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
        <p className="muted small">At least 10 characters. Share it with them, then let them change it.</p>

        <button type="submit" className="btn btn--primary" disabled={create.isPending} data-testid="member-submit">
          {create.isPending ? "Adding…" : "Add member"}
        </button>
      </form>

      {create.error ? (
        <p className="alert alert--error" role="alert">
          {create.error instanceof ApiError ? create.error.message : "Could not add this person."}
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
          setNotice(`Saved ${person.email}.`);
          setResetting(null);
          setNewPassword("");
        },
        onError: (error) => {
          setProblem(error instanceof ApiError ? error.message : "Could not save this change.");
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
          <caption className="sr-only">Team members and their access</caption>
          <thead>
            <tr>
              <th scope="col">Member</th>
              <th scope="col">Role</th>
              <th scope="col">Status</th>
              <th scope="col">Added</th>
              <th scope="col">Actions</th>
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
                  <td>{person.role === "owner" ? "Owner" : "Staff"}</td>
                  <td>
                    <span className={`badge badge--${person.is_active ? "confirmed" : "offline"}`}>
                      <span aria-hidden="true" className="badge__dot" />
                      {person.is_active ? "Active" : "Deactivated"}
                    </span>
                  </td>
                  <td className="nowrap">{formatDateTime(person.created_at)}</td>
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
                        {person.role === "owner" ? "Make staff" : "Make owner"}
                      </button>
                      <button
                        type="button"
                        className="btn btn--small"
                        disabled={update.isPending || (isSelf && person.is_active)}
                        title={isSelf && person.is_active ? "You cannot deactivate your own account" : undefined}
                        onClick={() => save(person.id, { is_active: !person.is_active })}
                      >
                        {person.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                      <button
                        type="button"
                        className="btn btn--small"
                        onClick={() => {
                          setResetting(resetting === person.id ? null : person.id);
                          setNewPassword("");
                        }}
                      >
                        {resetting === person.id ? "Cancel" : "Reset password"}
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
                        <label htmlFor={`new-password-${person.id}`}>New password</label>
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
                          Save password
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
