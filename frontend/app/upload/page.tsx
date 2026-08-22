import { Suspense } from "react";
import UploadClient from "./upload-client";

export const metadata = { title: "Analyze a dataset — SplitShield" };

export default function UploadPage() {
  return (
    <Suspense>
      <UploadClient />
    </Suspense>
  );
}
