import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';

class StocksView extends StatefulWidget {
  const StocksView({super.key});

  @override
  State<StocksView> createState() => _StocksViewState();
}

class _StocksViewState extends State<StocksView> {
  final _searchController = TextEditingController();
  String _filter = "";

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);
    var stocks = appState.stocks;

    if (_filter.isNotEmpty) {
      stocks = stocks.where((s) {
        final f = _filter.toLowerCase();
        return s.sku.toLowerCase().contains(f) ||
            (s.location?.toLowerCase().contains(f) ?? false) ||
            (s.itemName?.toLowerCase().contains(f) ?? false);
      }).toList();
    }

    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                "Inventory Stock Levels",
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: Colors.red.shade900,
                ),
              ),
              Row(
                children: [
                  ElevatedButton.icon(
                    onPressed: appState.isLoading
                        ? null
                        : appState.exportStocks,
                    icon: const Icon(Icons.download),
                    label: const Text("Export CSV"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green.shade50,
                      foregroundColor: Colors.green.shade900,
                    ),
                  ),
                  const SizedBox(width: 12),
                  ElevatedButton.icon(
                    onPressed: appState.isLoading ? null : appState.fetchStocks,
                    icon: const Icon(Icons.refresh),
                    label: const Text("Refresh"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red.shade50,
                      foregroundColor: Colors.red.shade900,
                    ),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 24),
          // Search box
          TextField(
            controller: _searchController,
            decoration: InputDecoration(
              hintText: "Search SKU or Description...",
              prefixIcon: const Icon(Icons.search),
              isDense: true,
              filled: true,
              fillColor: Colors.white,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(color: Colors.red.shade100),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(color: Colors.red.shade100),
              ),
              suffixIcon: _filter.isNotEmpty
                  ? IconButton(
                      icon: const Icon(Icons.clear, size: 18),
                      onPressed: () {
                        setState(() {
                          _searchController.clear();
                          _filter = "";
                        });
                      },
                    )
                  : null,
            ),
            onChanged: (val) {
              setState(() {
                _filter = val;
              });
            },
          ),
          const SizedBox(height: 24),
          Expanded(
            child: Container(
              width: double.infinity,
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.05),
                    blurRadius: 10,
                    spreadRadius: 2,
                  ),
                ],
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: appState.isLoading && appState.stocks.isEmpty
                    ? const Center(child: CircularProgressIndicator())
                    : appState.stocks.isEmpty
                    ? const Center(child: Text("No stock data available."))
                    : stocks.isEmpty
                    ? const Center(child: Text("No items match your search."))
                    : SingleChildScrollView(
                        scrollDirection: Axis.vertical,
                        child: SizedBox(
                          width: double.infinity,
                          child: DataTable(
                            headingRowColor: WidgetStateProperty.all(
                              Colors.red.shade50,
                            ),
                            columns: const [
                              DataColumn(
                                label: Text(
                                  'SKU',
                                  style: TextStyle(fontWeight: FontWeight.bold),
                                ),
                              ),
                              DataColumn(
                                label: Text(
                                  'Item name',
                                  style: TextStyle(fontWeight: FontWeight.bold),
                                ),
                              ),
                              DataColumn(
                                label: Text(
                                  'Location',
                                  style: TextStyle(fontWeight: FontWeight.bold),
                                ),
                              ),
                              DataColumn(
                                label: Text(
                                  'Qty',
                                  style: TextStyle(fontWeight: FontWeight.bold),
                                ),
                                numeric: true,
                              ),
                            ],
                            rows: stocks.map((stock) {
                              final itemName = stock.itemName ?? 'Unknown';
                              return DataRow(
                                cells: [
                                  DataCell(Text(stock.sku)),
                                  DataCell(Text(itemName)),
                                  DataCell(Text(stock.location ?? "-")),
                                  DataCell(
                                    Text(
                                      stock.stock.toString(),
                                      style: const TextStyle(
                                        fontWeight: FontWeight.bold,
                                        fontSize: 16,
                                        color: Colors.red,
                                      ),
                                    ),
                                  ),
                                ],
                              );
                            }).toList(),
                          ),
                        ),
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
