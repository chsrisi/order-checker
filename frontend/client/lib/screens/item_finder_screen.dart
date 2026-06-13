import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';

class ItemFinderScreen extends StatefulWidget {
  const ItemFinderScreen({super.key});

  @override
  State<ItemFinderScreen> createState() => _ItemFinderScreenState();
}

class _ItemFinderScreenState extends State<ItemFinderScreen> {
  final TextEditingController _searchController = TextEditingController();

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
    _searchController.dispose();
    super.dispose();
  }

  void _parseBarcode(String barcode) {
    // Format: AAA_AAA*XX*Pcs***DEMO
    // Interested in AAA_AAA (idbrng)
    if (barcode.contains('*')) {
      final parts = barcode.split('*');
      if (parts.isNotEmpty) {
        setState(() {
          _searchController.text = parts[0];
        });
      }
    }
  }

  void _handleSearch(AppState appState) {
    appState.searchItems(_searchController.text.trim());
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(16.0),
          child: TextField(
            controller: _searchController,
            decoration: InputDecoration(
              labelText: "Find Item (SKU or Name)",
              prefixIcon: const Icon(Icons.search),
              border: const OutlineInputBorder(),
              suffixIcon: IconButton(
                icon: const Icon(Icons.clear),
                onPressed: () {
                  _searchController.clear();
                },
              ),
            ),
            onSubmitted: (_) {
              if (_searchController.text.contains('*')) {
                _parseBarcode(_searchController.text);
              }
              _handleSearch(appState);
            },
          ),
        ),
        if (appState.isFetching && appState.foundItems.isEmpty)
          const LinearProgressIndicator(),
        Expanded(
          child: appState.foundItems.isEmpty
              ? const Center(child: Text("No items found"))
              : ListView.builder(
                  itemCount: appState.foundItems.length,
                  itemBuilder: (context, index) {
                    final item = appState.foundItems[index];
                    return ListTile(
                      title: Text(item.sku),
                      subtitle: Text(item.itemName ?? 'Unknown'),
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
                          item.location?.trim().isNotEmpty ?? false
                              ? item.location!
                              : 'N/A',
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
      ],
    );
  }
}
