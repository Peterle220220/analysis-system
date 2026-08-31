# FIXTURE — bpi19_slice.csv

Tài liệu **quan sát**, không phải lỗi tự cài. Fixture cắt từ dữ liệu thật và
bất biến kể từ khi commit; test đọc file đã commit, không cắt lại lúc chạy.

## Nguồn

- File gốc: `BPI_Challenge_2019.xes`
- SHA-256 file gốc: `af63bc687fc4152f2123b05c3af7772b37ef3fce2d3f67f812666c9e356baae7`
- Bộ dữ liệu: BPI Challenge 2019 (Purchase-to-Pay), 4TU.ResearchData
- Trích dẫn bắt buộc: van Dongen, B.F., *Dataset BPI Challenge 2019*.
  4TU.Centre for Research Data.
  https://doi.org/10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1

## Quy tắc cắt

Tất định tuyệt đối, không dùng random. Lấy nguyên case hoàn chỉnh — cắt giữa
case sẽ làm process mining ra một quy trình chưa từng xảy ra.

1. Sắp xếp toàn bộ case theo `case_id`.
2. Lượt 1 — dùng 50% ngân sách: lấy case đầu tiên của **mỗi variant chưa gặp**,
   để các đường đi hiếm cũng có mặt.
3. Lượt 2 — 50% còn lại: lấp bằng các case còn lại theo thứ tự `case_id`,
   nhờ đó variant phổ biến lặp lại nhiều lần và **tần suất variant có ý nghĩa**.
4. Case nào làm vượt ngân sách thì bỏ qua, không cắt ngắn.

## Quy mô

- Số case: **158**
- Số event: **5000**
- Số variant: **84**
- Số activity khác nhau: **23**
- Event/case: min 8 · trung vị 12 · max 464
- Khoảng thời gian: 2001-02-23T22:59:00.000Z → 2019-04-30T21:59:00.000Z

## Activity quan sát được

| Activity | Số event |
|---|---:|
| Record Invoice Receipt | 747 |
| Record Goods Receipt | 731 |
| Record Service Entry Sheet | 653 |
| Vendor creates invoice | 530 |
| Clear Invoice | 501 |
| SRM: In Transfer to Execution Syst. | 258 |
| SRM: Created | 213 |
| SRM: Complete | 213 |
| SRM: Awaiting Approval | 213 |
| SRM: Document Completed | 213 |
| SRM: Ordered | 213 |
| SRM: Change was Transmitted | 158 |
| Create Purchase Order Item | 158 |
| SRM: Deleted | 55 |
| Change Price | 44 |
| Cancel Invoice Receipt | 30 |
| Vendor creates debit memo | 23 |
| Remove Payment Block | 20 |
| SRM: Transfer Failed (E.Sys.) | 17 |
| Cancel Goods Receipt | 4 |
| Change Delivery Indicator | 2 |
| Delete Purchase Order Item | 2 |
| SRM: Transaction Completed | 2 |

## Vấn đề chất lượng quan sát được

| Hiện tượng | Số lượng | Ghi chú |
|---|---:|---|
| Event có `timestamp` trùng với event khác cùng case | 2901 | Lý do `event_seq` phải tồn tại: timestamp một mình không xác định được thứ tự |
| `resource` mang giá trị chuỗi `NONE` | 1224 | Null giả dạng chuỗi, không phải giá trị thiếu thật |
| `resource` trùng hệt `user` | 5000/5000 | Hai cột chở cùng một thông tin; giữ cả hai để A2 Profiler tự phát hiện |
| Case có activity lặp lại (rework) | 59 | Đầu vào cho phân tích rework ở Phase 4 |
| Ô rỗng ở cột `case_spend_area_text` | 42 | Giá trị thiếu thật |
| Ô rỗng ở cột `case_spend_classification_text` | 42 | Giá trị thiếu thật |
| Ô rỗng ở cột `case_sub_spend_area_text` | 42 | Giá trị thiếu thật |

## Ánh xạ cột

| Cột fixture | Nguồn trong XES |
|---|---|
| `case_id` | thuộc tính trace `concept:name` |
| `event_seq` | **không có trong nguồn** — vị trí của event trong case, lấy theo thứ tự tài liệu XES |
| `activity` | thuộc tính event `concept:name` |
| `timestamp` | thuộc tính event `time:timestamp` |
| `resource` | thuộc tính event `org:resource` |
| `user` | thuộc tính event `User` |
| `cumulative_net_worth_eur` | thuộc tính event `Cumulative net worth (EUR)` |
| `case_purchasing_document` | thuộc tính trace `Purchasing Document` |
| `case_item` | thuộc tính trace `Item` |
| `case_item_type` | thuộc tính trace `Item Type` |
| `case_item_category` | thuộc tính trace `Item Category` |
| `case_gr_based_inv_verif` | thuộc tính trace `GR-Based Inv. Verif.` |
| `case_goods_receipt` | thuộc tính trace `Goods Receipt` |
| `case_source` | thuộc tính trace `Source` |
| `case_purch_doc_category_name` | thuộc tính trace `Purch. Doc. Category name` |
| `case_company` | thuộc tính trace `Company` |
| `case_spend_classification_text` | thuộc tính trace `Spend classification text` |
| `case_spend_area_text` | thuộc tính trace `Spend area text` |
| `case_sub_spend_area_text` | thuộc tính trace `Sub spend area text` |
| `case_vendor` | thuộc tính trace `Vendor` |
| `case_name` | thuộc tính trace `Name` |
| `case_document_type` | thuộc tính trace `Document Type` |
