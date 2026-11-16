"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { PASSWORD_MIN, registerSchema, type RegisterValues } from "@/lib/validation";

export function RegisterForm() {
  const { register: createAccount } = useAuth();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: "", password: "", confirmPassword: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await createAccount(values.email.trim(), values.password);
      // Registered and signed in; the (auth) layout redirects to the dashboard.
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setError("email", { message: "An account with this email already exists." });
      } else {
        setFormError(errorMessage(error, "Couldn't create your account. Please try again."));
      }
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <Field id="email" label="Email" error={errors.email?.message}>
        {(props) => <Input {...props} type="email" autoComplete="email" autoFocus {...register("email")} />}
      </Field>
      <Field
        id="password"
        label="Password"
        error={errors.password?.message}
        hint={`At least ${PASSWORD_MIN} characters. A few random words make a strong one.`}
      >
        {(props) => <Input {...props} type="password" autoComplete="new-password" {...register("password")} />}
      </Field>
      <Field id="confirmPassword" label="Repeat password" error={errors.confirmPassword?.message}>
        {(props) => (
          <Input {...props} type="password" autoComplete="new-password" {...register("confirmPassword")} />
        )}
      </Field>
      {formError ? (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <Button type="submit" className="w-full" loading={isSubmitting}>
        Create account
      </Button>
    </form>
  );
}
