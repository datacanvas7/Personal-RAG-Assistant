import { z } from "zod";

// The password limits mirror the backend (12–128 characters) so people get the message
// before the round trip. The server remains the authority.
export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 128;

const email = z
  .string()
  .trim()
  .min(1, "Enter your email address")
  .pipe(z.email("Enter a valid email address"));

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Enter your password"),
});

export const registerSchema = z
  .object({
    email,
    password: z
      .string()
      .min(PASSWORD_MIN, `Use at least ${PASSWORD_MIN} characters`)
      .max(PASSWORD_MAX, `Use at most ${PASSWORD_MAX} characters`),
    confirmPassword: z.string().min(1, "Repeat your password"),
  })
  .refine((values) => values.password === values.confirmPassword, {
    path: ["confirmPassword"],
    message: "The passwords don't match",
  });

export type LoginValues = z.input<typeof loginSchema>;
export type RegisterValues = z.input<typeof registerSchema>;

/* ---- Documents ----------------------------------------------------------------------- */

export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"] as const;
/** Used until /settings reports the server's real limit; matches the API's default (25 MiB). */
export const DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

/** Why a file can't be uploaded, or null when it is fine. Mirrors the server's checks. */
export function validateUpload(
  file: { name: string; size: number },
  maxBytes: number = DEFAULT_MAX_UPLOAD_BYTES,
): string | null {
  const lower = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((extension) => lower.endsWith(extension))) {
    return "Unsupported file type. Use PDF, DOCX, TXT or Markdown.";
  }
  if (file.size === 0) return "This file is empty.";
  if (file.size > maxBytes) {
    return `This file is larger than the ${Math.round(maxBytes / (1024 * 1024))} MB limit.`;
  }
  return null;
}

/* ---- Settings ------------------------------------------------------------------------ */

export const TOP_K_MIN = 1;
export const TOP_K_MAX = 20;

export const retrievalSchema = z.object({
  topK: z.coerce
    .number<string | number>("Enter a whole number")
    .int("Enter a whole number")
    .min(TOP_K_MIN, `Use ${TOP_K_MIN} to ${TOP_K_MAX}`)
    .max(TOP_K_MAX, `Use ${TOP_K_MIN} to ${TOP_K_MAX}`),
  scoreThreshold: z.coerce
    .number<string | number>("Enter a number")
    .min(0, "Use a value from 0 to 1")
    .max(1, "Use a value from 0 to 1"),
});

export type RetrievalInput = z.input<typeof retrievalSchema>;
export type RetrievalValues = z.output<typeof retrievalSchema>;
