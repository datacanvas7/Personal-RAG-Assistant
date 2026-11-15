from pydantic import BaseModel, Field

from app.models import DocumentStatus
from app.services.analytics import Overview


class DocumentCounts(BaseModel):
    total: int
    ready: int
    processing: int  # includes documents waiting in the queue
    failed: int


class RecentActivity(BaseModel):
    days: int = Field(description="The window these counts cover, ending now.")
    documents_uploaded: int
    conversations_started: int
    questions_asked: int


class OverviewResponse(BaseModel):
    documents: DocumentCounts
    chunks: int
    conversations: int
    messages: int = Field(description="Questions and answers together.")
    questions: int
    answers: int
    cited_answers: int = Field(description="Answers that cite at least one of your documents.")
    recent_activity: RecentActivity

    @classmethod
    def from_overview(cls, overview: Overview) -> "OverviewResponse":
        counts = overview.counts
        return cls(
            documents=DocumentCounts(
                total=overview.total_documents,
                ready=overview.documents_with_status(DocumentStatus.READY),
                processing=overview.documents_with_status(DocumentStatus.PENDING)
                + overview.documents_with_status(DocumentStatus.PROCESSING),
                failed=overview.documents_with_status(DocumentStatus.FAILED),
            ),
            chunks=counts.chunks,
            conversations=counts.conversations,
            messages=counts.user_messages + counts.assistant_messages,
            questions=counts.user_messages,
            answers=counts.assistant_messages,
            cited_answers=counts.cited_answers,
            recent_activity=RecentActivity(
                days=overview.recent_days,
                documents_uploaded=counts.documents_since,
                conversations_started=counts.conversations_since,
                questions_asked=counts.questions_since,
            ),
        )
