import AppShell from "@/components/app-shell";
import { CleanContent } from "@/components/dataset-pages";

export default async function CleanPage({ params }: { params: Promise<{ dataset: string }> }) {
  const { dataset } = await params;
  return <AppShell><CleanContent dataset={dataset} /></AppShell>;
}
