"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { loginSchema, type LoginValues } from "@/lib/validation";

export function LoginForm() {
  const { login } = useAuth();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values.email.trim(), values.password);
      // The (auth) layout sees the new session and redirects to the dashboard.
    } catch (error) {
      setFormError(
        error instanceof ApiError && error.status === 401
          ? "Wrong email or password."
          : errorMessage(error, "Couldn't sign you in. Please try again."),
      );
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <Field id="email" label="Email" error={errors.email?.message}>
        {(props) => <Input {...props} type="email" autoComplete="email" autoFocus {...register("email")} />}
      </Field>
      <Field id="password" label="Password" error={errors.password?.message}>
        {(props) => (
          <Input {...props} type="password" autoComplete="current-password" {...register("password")} />
        )}
      </Field>
      {formError ? (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <Button type="submit" className="w-full" loading={isSubmitting}>
        Sign in
      </Button>
    </form>
  );
}
