"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError, unwrap } from "@/lib/api/client";

type Mode = "login" | "register";

function safeNext(next: string | null): string {
  // Only allow same-site relative paths to avoid open redirects.
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const params = useSearchParams();
  const [fields, setFields] = useState({ name: "", email: "", password: "" });

  const submit = useMutation({
    mutationFn: () =>
      mode === "login"
        ? unwrap(api.POST("/api/v1/auth/login", { body: fields }))
        : unwrap(
            api.POST("/api/v1/auth/register", {
              body: { ...fields, name: fields.name || null },
            }),
          ),
    onSuccess: () => {
      router.replace(safeNext(params.get("next")));
      router.refresh();
    },
  });

  const fieldErrors = submit.error instanceof ApiError ? submit.error.fieldErrors() : {};
  const formError = submit.error && Object.keys(fieldErrors).length === 0 ? submit.error : null;

  const set = (k: keyof typeof fields) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setFields((f) => ({ ...f, [k]: e.target.value }));

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        submit.mutate();
      }}
      noValidate
    >
      <div>
        <h1 className="text-3xl font-semibold">
          {mode === "login" ? "Sign in" : "Create your account"}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {mode === "login" ? (
            <>
              New here?{" "}
              <Link
                href="/register"
                className="font-medium text-foreground underline underline-offset-4"
              >
                Create an account
              </Link>
            </>
          ) : (
            <>
              Already have one?{" "}
              <Link
                href="/login"
                className="font-medium text-foreground underline underline-offset-4"
              >
                Sign in
              </Link>
            </>
          )}
        </p>
      </div>

      {mode === "register" && (
        <Field id="name" label="Your name" error={fieldErrors.name}>
          <Input id="name" autoComplete="name" value={fields.name} onChange={set("name")} />
        </Field>
      )}
      <Field id="email" label="Work email" error={fieldErrors.email}>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={fields.email}
          onChange={set("email")}
        />
      </Field>
      <Field
        id="password"
        label="Password"
        error={fieldErrors.password}
        hint={mode === "register" ? "At least 10 characters." : undefined}
      >
        <Input
          id="password"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          value={fields.password}
          onChange={set("password")}
        />
      </Field>

      {formError && <ErrorState error={formError} />}

      <Button type="submit" className="w-full" size="lg" disabled={submit.isPending}>
        {submit.isPending
          ? mode === "login"
            ? "Signing in…"
            : "Creating account…"
          : mode === "login"
            ? "Sign in"
            : "Create account"}
      </Button>
    </form>
  );
}

export function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p className="text-sm text-rose" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}
