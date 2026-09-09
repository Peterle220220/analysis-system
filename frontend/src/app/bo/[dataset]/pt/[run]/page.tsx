import AppShell from "@/components/app-shell";
import { RoundContent } from "@/components/dataset-pages";

export default async function RoundPage({ params }: { params: Promise<{ dataset: string; run: string }> }) {
  const { dataset, run } = await params;
  return <AppShell><RoundContent dataset={dataset} round={run} /></AppShell>;
}
