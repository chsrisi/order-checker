import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';

class ItemFinderView extends StatefulWidget {
  const ItemFinderView({super.key});

  @override
  State<ItemFinderView> createState() => _ItemFinderViewState();
}

class _ItemFinderViewState extends State<ItemFinderView> {
  final TextEditingController _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);
    final foundItems = appState.foundItems;

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(16.0),
          child: TextField(
            controller: _searchController,
            decoration: const InputDecoration(
              labelText: "Find Item (SKU or Name)",
              prefixIcon: Icon(Icons.search),
              border: OutlineInputBorder(),
            ),
            onSubmitted: (value) => appState.searchItems(value.trim()),
          ),
        ),
        if (appState.isLoading && foundItems.isEmpty)
          const LinearProgressIndicator(),
        Expanded(
          child: foundItems.isEmpty && !appState.isLoading
              ? const Center(child: Text("No items found"))
              : ListView.builder(
                  itemCount: foundItems.length,
                  itemBuilder: (context, index) {
                    final item = foundItems[index];
                    return Card(
                      margin: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 4,
                      ),
                      child: ListTile(
                        leading: const CircleAvatar(
                          child: Icon(Icons.inventory_2),
                        ),
                        title: Text("${item.sku} - ${item.itemName}"),
                        subtitle: Text(
                          "Location: ${item.location}",
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                            color: Colors.red,
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
