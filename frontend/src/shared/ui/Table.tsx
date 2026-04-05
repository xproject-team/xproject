/**
 * Table — generic reusable table with typed columns and row data.
 * Feature components use this instead of writing raw <table> HTML.
 */
interface Column<T> {
  header: string
  accessor: keyof T | ((row: T) => string | number)
}

interface TableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyField: keyof T
}

export function Table<T>({ columns, data, keyField }: TableProps<T>) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-left">
        <thead className="text-xs text-[#4A5568] uppercase bg-[#F7FAFC] border-b border-[#E2E8F0]">
          <tr>
            {columns.map((col) => (
              <th key={col.header} className="px-4 py-3">{col.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={String(row[keyField])} className="border-b border-[#E2E8F0]">
              {columns.map((col) => (
                <td key={col.header} className="px-4 py-3">
                  {typeof col.accessor === 'function'
                    ? col.accessor(row)
                    : String(row[col.accessor])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
