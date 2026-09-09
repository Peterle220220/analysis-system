import { RoundContent } from "@/components/dataset-pages";

export default async function RoundPage({ params }: { params: Promise<{ dataset: string; run: string }> }) {
  const { dataset, run } = await params;
  return <RoundContent dataset={dataset} round={run} />;
}
