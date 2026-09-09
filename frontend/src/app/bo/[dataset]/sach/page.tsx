import { CleanContent } from "@/components/dataset-pages";

export default async function CleanPage({ params }: { params: Promise<{ dataset: string }> }) {
  const { dataset } = await params;
  return <CleanContent dataset={dataset} />;
}
