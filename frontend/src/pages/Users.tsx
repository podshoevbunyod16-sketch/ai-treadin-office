import { FormEvent, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field, Modal, useAction } from "../components/ui";
import { fmtIso } from "../format";
import { useApi } from "../hooks";
import type { User } from "../types";

export default function UsersPage() {
  const { data, error, reload } = useApi<User[]>("/api/users");
  const { user: me } = useAuth();
  const [creating, setCreating] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("trader");
  const [formErr, setFormErr] = useState<string | null>(null);
  const act = useAction();

  async function create(e: FormEvent) {
    e.preventDefault();
    setFormErr(null);
    try {
      await api("/api/users", { method: "POST", body: { username, password, role } });
      setCreating(false);
      setUsername("");
      setPassword("");
      reload();
    } catch (err) {
      setFormErr((err as Error).message);
    }
  }
  async function patch(u: User, body: Record<string, unknown>, msg: string) {
    await act.run(() => api(`/api/users/${u.id}`, { method: "PATCH", body }), msg);
    reload();
  }
  async function resetPw(u: User) {
    const pw = prompt(`Новый пароль для ${u.username} (≥10 символов, буквы и цифры):`);
    if (pw) await patch(u, { password: pw }, "Пароль изменён, сессии пользователя завершены");
  }
  async function remove(u: User) {
    if (!confirm(`Удалить пользователя ${u.username}?`)) return;
    await act.run(() => api(`/api/users/${u.id}`, { method: "DELETE" }), "Пользователь удалён");
    reload();
  }

  return (
    <div className="page">
      <div className="page-head">
        <h1>Пользователи</h1>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          + Пользователь
        </button>
      </div>
      <p className="muted">
        Роли: <b>admin</b> — всё, включая пользователей и удаление счетов; <b>trader</b> — торговля, счета, боты; <b>viewer</b> — только просмотр.
      </p>
      <ErrorBox error={error} />
      <table className="table">
        <thead>
          <tr>
            <th>Имя</th>
            <th>Роль</th>
            <th>Статус</th>
            <th>Создан</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(data ?? []).map((u) => (
            <tr key={u.id}>
              <td>{u.username}</td>
              <td>
                <select value={u.role} disabled={u.id === me?.id} onChange={(e) => patch(u, { role: e.target.value }, "Роль изменена")}>
                  <option value="admin">admin</option>
                  <option value="trader">trader</option>
                  <option value="viewer">viewer</option>
                </select>
              </td>
              <td className={u.is_active ? "pos" : "neg"}>{u.is_active ? "активен" : "заблокирован"}</td>
              <td>{fmtIso(u.created_at)}</td>
              <td className="actions">
                {u.id !== me?.id && (
                  <>
                    <button className="btn btn-sm btn-ghost" onClick={() => patch(u, { is_active: !u.is_active }, u.is_active ? "Заблокирован" : "Разблокирован")}>
                      {u.is_active ? "Заблокировать" : "Разблокировать"}
                    </button>
                    <button className="btn btn-sm btn-ghost" onClick={() => resetPw(u)}>
                      Сменить пароль
                    </button>
                    <button className="btn btn-sm btn-ghost danger" onClick={() => remove(u)}>
                      Удалить
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {creating && (
        <Modal title="Новый пользователь" onClose={() => setCreating(false)}>
          <form className="form" onSubmit={create}>
            <ErrorBox error={formErr} />
            <Field label="Имя пользователя">
              <input value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} />
            </Field>
            <Field label="Пароль" hint="Минимум 10 символов, буквы и цифры/символы">
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" />
            </Field>
            <Field label="Роль">
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="trader">trader</option>
                <option value="viewer">viewer</option>
                <option value="admin">admin</option>
              </select>
            </Field>
            <button className="btn btn-primary">Создать</button>
          </form>
        </Modal>
      )}
    </div>
  );
}
