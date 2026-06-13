import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';

class StocksView extends StatelessWidget {
  final int subIndex;
  const StocksView({super.key, required this.subIndex});

  @override
  Widget build(BuildContext context) {
    if (subIndex == 0) {
      return const StocksInput();
    } else {
      return const StocksHistory();
    }
  }
}

class StocksInput extends StatefulWidget {
  const StocksInput({super.key});

  @override
  State<StocksInput> createState() => _StocksInputState();
}

class _StocksInputState extends State<StocksInput> {
  final _skuController = TextEditingController();
  final _qtyController = TextEditingController();
  final _focusNode = FocusNode();
  final _qtyFocusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final appState = Provider.of<AppState>(context, listen: false);
      appState.onShowMessage = (message, {isError = false, isAlert = false}) {
        if (!mounted) return;
        if (isAlert) {
          showDialog(
            context: context,
            builder: (context) => AlertDialog(
              title: Text(isError ? "Error" : "Notification"),
              content: Text(message),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text("OK"),
                ),
              ],
            ),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(message),
              backgroundColor: isError ? Colors.red : null,
            ),
          );
        }
      };
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        final appState = Provider.of<AppState>(context, listen: false);
        appState.onShowMessage = null;
      }
    });
    _skuController.dispose();
    _qtyController.dispose();
    _focusNode.dispose();
    _qtyFocusNode.dispose();
    super.dispose();
  }

  void _parseBarcode(String barcode) {
    // Format: AAA_AAA*XX*Pcs***DEMO
    // Interested in AAA_AAA (idbrng)
    if (barcode.contains('*')) {
      final parts = barcode.split('*');
      if (parts.isNotEmpty) {
        setState(() {
          _skuController.text = parts[0];
        });
      }
    }
  }

  void _submit(String mode) {
    final appState = Provider.of<AppState>(context, listen: false);
    final sku = _skuController.text.trim();
    final qty = int.tryParse(_qtyController.text.trim());

    if (sku.isEmpty || qty == null) {
      appState.onShowMessage?.call(
        "Please enter valid SKU and Qty.",
        isError: true,
      );
      return;
    }

    appState.updateStock(sku, qty, mode: mode).then((_) {
      setState(() {
        _skuController.clear();
        _qtyController.clear();
        _focusNode.requestFocus();
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);
    return Padding(
      padding: const EdgeInsets.all(16.0),
      child: Column(
        children: [
          TextField(
            controller: _skuController,
            focusNode: _focusNode,
            decoration: const InputDecoration(
              labelText: "SKU (Scan Barcode)",
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.qr_code_scanner),
            ),
            onSubmitted: (_) {
              if (_skuController.text.contains('*')) {
                _parseBarcode(_skuController.text);
              }
              _qtyFocusNode.requestFocus();
            },
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _qtyController,
            focusNode: _qtyFocusNode,
            decoration: const InputDecoration(
              labelText: "Quantity (Stock)",
              border: OutlineInputBorder(),
            ),
            keyboardType: TextInputType.number,
            onSubmitted: (_) => _submit("set"),
          ),
          const SizedBox(height: 24),
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 50,
                  child: ElevatedButton(
                    onPressed: appState.isSaving ? null : () => _submit("add"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.orange,
                      foregroundColor: Colors.white,
                    ),
                    child: appState.isSaving
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Text("Add Stock"),
                  ),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: SizedBox(
                  height: 50,
                  child: ElevatedButton(
                    onPressed: appState.isSaving ? null : () => _submit("set"),
                    child: appState.isSaving
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text("Set Stock"),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class StocksHistory extends StatefulWidget {
  const StocksHistory({super.key});

  @override
  State<StocksHistory> createState() => _StocksHistoryState();
}

class _StocksHistoryState extends State<StocksHistory> {
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
            (s.itemName?.toLowerCase().contains(f) ?? false) ||
            (s.location?.toLowerCase().contains(f) ?? false);
      }).toList();
    }

    if (appState.isFetching && appState.stocks.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
          child: TextField(
            controller: _searchController,
            decoration: InputDecoration(
              hintText: "Filter SKU or Description...",
              prefixIcon: const Icon(Icons.search),
              isDense: true,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
              ),
              suffixIcon: _filter.isNotEmpty
                  ? IconButton(
                      icon: const Icon(Icons.clear),
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
        ),
        Expanded(
          child: appState.stocks.isEmpty
              ? const Center(child: Text("No stock records found."))
              : stocks.isEmpty
              ? const Center(child: Text("No items match your filter."))
              : RefreshIndicator(
                  onRefresh: () => appState.fetchStocks(),
                  child: ListView.builder(
                    itemCount: stocks.length,
                    itemBuilder: (context, index) {
                      final stock = stocks[index];
                      final itemName = stock.itemName ?? 'Unknown';
                      return ListTile(
                        title: Text(stock.sku),
                        subtitle: Text(
                          "$itemName | ${stock.location ?? "No Location"}",
                        ),
                        trailing: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 6,
                          ),
                          decoration: BoxDecoration(
                            color: Colors.blue.withValues(alpha: 0.1),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Text(
                            stock.stock.toString(),
                            style: const TextStyle(
                              fontWeight: FontWeight.bold,
                              fontSize: 18,
                              color: Colors.blue,
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                ),
        ),
      ],
    );
  }
}
