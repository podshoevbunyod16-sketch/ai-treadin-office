import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ParamForm } from "../components/ParamForm";
import { AuthProvider } from "../auth";
import LoginPage from "../pages/Login";
import type { ParamDef } from "../types";

afterEach(() => vi.restoreAllMocks());

const defs: ParamDef[] = [
  { key: "fast", label: "Быстрая MA", type: "int", default: 10, min: 2, max: 500, step: null, help: "" },
  { key: "allow_short", label: "Разрешить шорт", type: "bool", default: true, min: null, max: null, step: null, help: "" },
];

describe("ParamForm", () => {
  it("renders params and emits typed changes", () => {
    const onChange = vi.fn();
    render(<ParamForm defs={defs} values={{ fast: 10, allow_short: true }} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Быстрая MA"), { target: { value: "12" } });
    expect(onChange).toHaveBeenLastCalledWith({ fast: 12, allow_short: true });
    fireEvent.click(screen.getByLabelText("Разрешить шорт"));
    expect(onChange).toHaveBeenLastCalledWith({ fast: 10, allow_short: false });
  });
});

describe("LoginPage", () => {
  it("shows the first-run admin setup when the server requires it", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ setup_required: true }), { status: 200 }));
    await act(async () => {
      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>,
      );
    });
    expect(await screen.findByText("Создать администратора")).toBeTruthy();
    expect(screen.getByLabelText("Повторите пароль")).toBeTruthy();
  });

  it("validates password confirmation before calling the API", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ setup_required: true }), { status: 200 }));
    await act(async () => {
      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>,
      );
    });
    fireEvent.change(await screen.findByLabelText("Имя пользователя"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "Secret-pass-1" } });
    fireEvent.change(screen.getByLabelText("Повторите пароль"), { target: { value: "other" } });
    await act(async () => {
      fireEvent.click(screen.getByText("Создать администратора"));
    });
    expect(screen.getByText("Пароли не совпадают")).toBeTruthy();
    expect(f).toHaveBeenCalledTimes(1);
  });
});
