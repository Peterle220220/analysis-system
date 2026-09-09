import AppShell from "@/components/app-shell";
import { DatasetContent } from "@/components/dataset-pages";

export default async function DatasetPage({ params }: { params: Promise<{ dataset: string }> }) {
  const { dataset } = await params;
  return <AppShell><DatasetContent dataset={dataset} /></AppShell>;
}
