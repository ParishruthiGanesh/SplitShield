import AuditClient from "./audit-client";

export const metadata = { title: "Audit — SplitShield" };

export default async function AuditPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return <AuditClient jobId={jobId} />;
}
