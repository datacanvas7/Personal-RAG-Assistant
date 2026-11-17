import type { Metadata } from "next";
import { Suspense } from "react";

import { ChatView } from "@/components/chat/chat-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Chat" };

export default function ChatPage() {
  // useSearchParams (the open conversation lives in ?c=) needs a Suspense boundary.
  return (
    <Suspense fallback={<Skeleton className="h-[60dvh] w-full" />}>
      <ChatView />
    </Suspense>
  );
}
