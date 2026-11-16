import type { Metadata } from "next";

import { Overview } from "@/components/dashboard/overview";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return <Overview />;
}
