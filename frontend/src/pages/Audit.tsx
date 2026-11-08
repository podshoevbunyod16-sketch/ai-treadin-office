import { useState } from "react";
import { Empty, ErrorBox } from "../components/ui";
import { fmtIso } from "../format";
import { useApi } from "../hooks";
import type { AuditRow } from "../types";

export default function AuditPage() {
  const [action, setAction] = useState("");
  const { data, error, reload, loading } = useApi<AuditRow[]>(`/api/audit?limit=500${action ? `&action=${encodeURIComponent(action)}` : ""}`);
  return (
    <div className="page">
      <div className="page-head">
        <h1>Журнал аудита</h1>
        <div className="row gap-s">
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">Все действия</option>
            <option value="trade">Торговые операции</option>
            <option value="bot">Боты</option>
            <option value="account">Счета</option>
            <option value="auth">Вход в систему</option>
            <option value="user">Пользователи</option>
          </select>
          <button className="btn btn-sm" onClick={reload} disabled={loading}>
            Обновить
          </button>
        </div>
      </div>
      <ErrorBox error={error} />
      {data && data.length === 0 && <Empty>Записей нет</Empty>}
      {data && data.length > 0 && (
        <table className="table compact">
          <thead>
            <tr>
              <th>Время</th>
              <th>Пользователь</th>
              <th>Действие</th>
              <th>Объект</th>
              <th>Результат</th>
              <th>Детали</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.id}>
                <td>{fmtIso(r.ts)}</td>
                <td>{r.username ?? "—"}</td>
                <td>{r.action}</td>
                <td>{r.target ?? "—"}</td>
                <td className={r.ok ? "pos" : "neg"}>{r.ok ? "успех" : "ошибка"}</td>
                <td className="mono small details-cell">{r.details ? JSON.stringify(r.details) : ""}</td>
                <td>{r.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
